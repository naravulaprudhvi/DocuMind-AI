import re

WHITESPACE_RE = re.compile(r"[ \t]+")
MULTI_NEWLINES_RE = re.compile(r"\n{3,}")
SENTENCE_RE = re.compile(r"[.!?]\s")


def clean_text(text: str) -> str:
    """Normalizes excessive whitespace and control characters."""
    lines = [WHITESPACE_RE.sub(" ", line).strip() for line in text.splitlines()]
    text = "\n".join(lines)
    text = MULTI_NEWLINES_RE.sub("\n\n", text)
    return text.strip()


def split_text_into_chunks(text: str, chunk_size: int = 500, chunk_overlap: int = 100) -> list[str]:
    """
    Splits text into chunks of approximately `chunk_size` characters with `chunk_overlap`.
    Prefers splitting on paragraph breaks, then sentence breaks, then word boundaries.
    """
    text = clean_text(text)
    if not text:
        return []

    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    total_len = len(text)

    while start < total_len:
        end = start + chunk_size

        if end >= total_len:
            chunk = text[start:].strip()
            if chunk:
                chunks.append(chunk)
            break

        # Look for natural breaking points near the end boundary (last 100 chars)
        window_start = max(start, end - 100)
        search_window = text[window_start:end]

        # 1. Paragraph boundary (\n\n)
        last_para = search_window.rfind("\n\n")
        if last_para != -1:
            split_point = window_start + last_para + 2
        else:
            # 2. Sentence boundary (. or ! or ? followed by space)
            sentence_matches = list(SENTENCE_RE.finditer(search_window))
            if sentence_matches:
                split_point = window_start + sentence_matches[-1].end()
            else:
                # 3. Line break (\n)
                last_line = search_window.rfind("\n")
                if last_line != -1:
                    split_point = window_start + last_line + 1
                else:
                    # 4. Word boundary (' ')
                    last_space = search_window.rfind(" ")
                    if last_space != -1:
                        split_point = window_start + last_space + 1
                    else:
                        split_point = end

        chunk = text[start:split_point].strip()
        if chunk:
            chunks.append(chunk)

        # Advance start with overlap
        start = max(start + 1, split_point - chunk_overlap)

    return chunks


def chunk_document_pages(pages: list[dict], chunk_size: int = 500, chunk_overlap: int = 100) -> list[dict]:
    """
    Takes a list of page dicts: [{'page_number': 1, 'text': '...'}]
    and returns a flat list of chunk dicts:
    [
        {
            'page_number': 1,
            'chunk_text': '...',
            'chunk_index': 0
        },
        ...
    ]
    """
    all_chunks = []
    chunk_index = 0

    for page_data in pages:
        page_num = page_data.get("page_number", 1)
        raw_text = page_data.get("text", "")
        page_chunks = split_text_into_chunks(raw_text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)

        for text in page_chunks:
            all_chunks.append({
                "page_number": page_num,
                "chunk_text": text,
                "chunk_index": chunk_index
            })
            chunk_index += 1

    return all_chunks
