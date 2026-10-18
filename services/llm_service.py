from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from services.retrieval import STOP_WORDS, WORD_RE, build_rag_prompt

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?\n])\s+")


_working_gemini_model = "gemini-3.5-flash-lite"


def call_gemini_api(system_instruction: str, user_prompt: str, api_key: str) -> str:
    """Invokes Google Gemini via REST API using standard library urllib with model fallback."""
    global _working_gemini_model
    candidate_models = [
        "gemini-3.5-flash-lite",
        "gemini-flash-lite-latest",
        "gemini-3.5-flash",
        "gemini-flash-latest",
    ]
    models_to_try = [_working_gemini_model] + [m for m in candidate_models if m != _working_gemini_model]

    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
        payload = {
            "system_instruction": {
                "parts": [{"text": system_instruction}]
            },
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_prompt}]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "maxOutputTokens": 2048,
            },
        }

        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=12) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        text_parts = [
                            p.get("text", "")
                            for p in parts
                            if not p.get("thought") and p.get("text")
                        ]
                        if text_parts:
                            _working_gemini_model = model_name
                            return "".join(text_parts).strip()
        except urllib.error.HTTPError:
            continue
        except Exception:  # noqa: BLE001, S112
            continue

    return ""


def call_openai_api(system_instruction: str, user_prompt: str, api_key: str) -> str:
    """Invokes OpenAI Chat Completion API using standard library urllib."""
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "gpt-3.5-turbo",
        "messages": [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        "max_tokens": 600,
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=25) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "").strip()
        return "OpenAI API returned an empty response."
    except urllib.error.HTTPError as e:
        return f"OpenAI API HTTP Error {e.code}: {e.read().decode('utf-8', errors='ignore')}"
    except Exception as e:  # noqa: BLE001
        return f"OpenAI connection error: {e}"


def call_ollama_api(
    system_instruction: str,
    user_prompt: str,
    base_url: str = "http://localhost:11434",
    model: str = "llama3",
) -> str:
    """Invokes local Ollama server endpoint for offline, fully private local LLM generation."""
    endpoint = f"{base_url.rstrip('/')}/api/generate"
    payload = {
        "model": model,
        "prompt": f"<system>\n{system_instruction}\n</system>\n\n<user>\n{user_prompt}\n</user>",
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 750,
        },
    }

    try:
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status == 200:
                data = json.loads(response.read().decode("utf-8"))
                return data.get("response", "").strip()
    except Exception:  # noqa: BLE001
        return ""
    return ""


def generate_local_extractive_answer(query: str, retrieved_chunks: list[dict[str, Any]]) -> str:
    """
    Intelligent fallback when no external LLM API key is configured.
    Synthesizes the most relevant statements from retrieved chunks with citations.
    """
    if not retrieved_chunks:
        return (
            "Hello! I am **DocuMind AI**, your document intelligence and conversational assistant.\n\n"
            "You can ask me questions directly, or attach documents (PDF, Word) using the **+** button below "
            "to perform grounded document analysis, semantic search, and summary extraction.\n\n"
            "*(Tip: To enable full generative AI answers for general questions and custom reasoning, "
            "ensure your `GEMINI_API_KEY` is added to your `.env` file.)*"
        )

    # Extract keywords from query
    keywords = [
        w.lower()
        for w in WORD_RE.findall(query)
        if w.lower() not in STOP_WORDS
    ]

    scored_sentences = []
    for c in retrieved_chunks:
        text = c["text"]
        sentences = SENTENCE_SPLIT_RE.split(text)
        for s in sentences:
            clean_s = s.strip()
            if len(clean_s) > 15:
                # Count matching query keywords
                match_count = sum(1 for kw in keywords if kw in clean_s.lower())
                scored_sentences.append({
                    "sentence": clean_s,
                    "score": match_count * 2.0 + c["similarity_score"],
                    "document_name": c["document_name"],
                    "page_number": c["page_number"],
                })

    scored_sentences.sort(key=lambda x: x["score"], reverse=True)
    top_sentences = scored_sentences[:4]

    if not top_sentences:
        best_chunk = retrieved_chunks[0]
        return (
            f"Based on **{best_chunk['document_name']}** (Page {best_chunk['page_number']}):\n\n"
            f"> {best_chunk['text'][:350]}...\n\n"
            f"*(Extracted via DocuMind RAG semantic vector search. Add `GEMINI_API_KEY` to `.env` or run Ollama locally to enable generative LLM answers.)*"
        )

    response_lines = ["Based on the retrieved document context:\n"]
    seen_text = set()
    for item in top_sentences:
        st = item["sentence"]
        if st not in seen_text:
            seen_text.add(st)
            response_lines.append(f"• {st} *[{item['document_name']}, Page {item['page_number']}]*")

    response_lines.append("\n*(Extracted via DocuMind RAG semantic vector search. Add `GEMINI_API_KEY` to `.env` or run Ollama locally to enable generative LLM answers.)*")
    return "\n".join(response_lines)


def generate_rag_response(
    query: str,
    retrieved_chunks: list[dict[str, Any]],
    chat_history: list[dict[str, str]] | None = None,
    provider: str | None = None,
) -> str:
    """
    Generates a grounded RAG response using Gemini, local Ollama, OpenAI,
    or the contextual extractor fallback based on configured provider.
    """
    system_instruction, user_prompt = build_rag_prompt(query, retrieved_chunks, chat_history)

    target_provider = (provider or os.getenv("LLM_PROVIDER", "gemini")).lower()

    # 1. Local Ollama Provider
    if target_provider in ("ollama", "local"):
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        model = os.getenv("OLLAMA_MODEL", "llama3")
        ollama_ans = call_ollama_api(system_instruction, user_prompt, base_url, model)
        if ollama_ans and ollama_ans.strip():
            return ollama_ans

    # 2. Gemini Provider (Default if API key is present)
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key and target_provider != "openai":
        answer = call_gemini_api(system_instruction, user_prompt, gemini_key)
        if answer and answer.strip():
            return answer

    # 3. OpenAI Provider
    openai_key = os.getenv("OPENAI_API_KEY")
    if openai_key:
        answer = call_openai_api(system_instruction, user_prompt, openai_key)
        if answer and answer.strip():
            return answer

    # 4. Fallback to intelligent local extractor
    return generate_local_extractive_answer(query, retrieved_chunks)
