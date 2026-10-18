from __future__ import annotations

import json
import os
import re
from typing import Any

from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from models.document import Document, DocumentChunk
from routes.auth import login_required

summaries_bp = Blueprint("summaries", __name__)

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?\n])\s+")
JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)

SUMMARY_KEYWORDS = frozenset({
    "developed", "designed", "implemented", "managed", "skills", "experience", "technologies",
    "revenue", "profit", "growth", "strategy", "cost", "investment", "financial",
    "agreement", "obligations", "liability", "compliance", "terms", "parties",
    "methodology", "results", "analysis", "conclusion", "system", "performance", "architecture",
    "engineered", "objective", "findings", "recommendations",
})


def generate_document_summary(doc: Any, chunks: list[Any]) -> dict[str, Any]:
    """
    Generates a structured executive summary, key takeaways,
    and metadata statistics from document chunks.
    """
    if not chunks:
        return {
            "overview": "No text content available to summarize.",
            "takeaways": [],
            "word_count": 0,
            "char_count": 0,
            "estimated_read_time_min": 0,
            "chunk_count": 0,
        }

    full_text = " ".join(c.chunk_text for c in chunks)
    words = full_text.split()
    word_count = len(words)
    char_count = len(full_text)
    read_time = max(1, round(word_count / 200))

    # Extract high-value sentences for overview and key points
    sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(full_text) if len(s.strip()) > 25]

    # Executive Overview default
    overview_sentences = sentences[:3]
    overview = " ".join(overview_sentences) if overview_sentences else full_text[:300] + "..."

    # Key Takeaways default (broadened for contracts, finance, science, reports, manuals, resumes)
    takeaway_candidates = [
        s for s in sentences[2:]
        if len(s) < 220 and any(kw in s.lower() for kw in SUMMARY_KEYWORDS)
    ]

    if len(takeaway_candidates) < 3 and len(sentences) > 3:
        step = max(1, len(sentences) // 4)
        takeaway_candidates = sentences[1::step][:5]

    takeaways = takeaway_candidates[:5]

    # If Gemini API Key is available, generate an enhanced AI summary
    gemini_key = os.getenv("GEMINI_API_KEY")
    if gemini_key:
        from services.llm_service import call_gemini_api
        doc_name = getattr(doc, "filename", "Document")
        prompt = (
            f"Generate a comprehensive executive summary for document '{doc_name}'.\n"
            f"Document text:\n{full_text[:4000]}\n\n"
            "Format your reply as valid JSON with keys:\n"
            "\"overview\": A concise, high-impact 2-3 sentence overview paragraph capturing the document's core purpose and key insights.\n"
            "\"takeaways\": A list of 4-6 high-value bullet point takeaways (insights, data points, or conclusions) as strings."
        )
        try:
            gemini_res = call_gemini_api(
                "You are an executive document analyst. Return valid JSON only.",
                prompt,
                gemini_key,
            )
            match = JSON_BLOCK_RE.search(gemini_res)
            if match:
                parsed = json.loads(match.group(0))
                if parsed.get("overview") and parsed.get("takeaways"):
                    overview = str(parsed["overview"]).strip()
                    takeaways = [str(t).strip() for t in parsed["takeaways"] if str(t).strip()]
        except Exception:  # noqa: BLE001, S110
            pass

    return {
        "overview": overview,
        "takeaways": takeaways,
        "word_count": word_count,
        "char_count": char_count,
        "estimated_read_time_min": read_time,
        "chunk_count": len(chunks),
    }


@summaries_bp.route("/documents/<int:doc_id>/summary", methods=["GET", "POST"])
@login_required
def view_summary(doc_id: int):
    user_id = session.get("user_id")
    doc: Any = Document.query.filter_by(document_id=doc_id, user_id=user_id).first_or_404()

    from services.cache_service import summary_cache
    cache_key = f"doc_summary_{doc.document_id}"
    cached = summary_cache.get(cache_key)
    if cached is not None:
        summary_data, chunks_count = cached
        return render_template("summary.html", doc=doc, summary=summary_data, chunks_count=chunks_count)

    chunks = (
        DocumentChunk.query.filter_by(document_id=doc.document_id)
        .order_by(DocumentChunk.page_number, DocumentChunk.chunk_id)
        .all()
    )

    summary_data = generate_document_summary(doc, chunks)
    summary_cache.set(cache_key, (summary_data, len(chunks)))
    return render_template("summary.html", doc=doc, summary=summary_data, chunks_count=len(chunks))
