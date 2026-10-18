"""
DocuMind AI — Security & Data Privacy Service
Provides enterprise-grade security features:
- PII (Personally Identifiable Information) detection & privacy masking
- Indirect prompt injection defense & input sanitization
- Path traversal & upload sandbox validation
- Cryptographic SHA-256 file integrity verification
- Security audit logging
- GDPR/CCPA data export & complete cryptographic erasure helpers
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import re
from typing import Any

logger = logging.getLogger("documind.security")

# Regex patterns for sensitive PII detection
PII_PATTERNS: dict[str, re.Pattern] = {
    "CREDIT_CARD": re.compile(
        r"\b(?:4[0-9]{12}(?:[0-9]{3})?|5[1-5][0-9]{14}|3[47][0-9]{13}|3(?:0[0-5]|[68][0-9])[0-9]{11}|6(?:011|5[0-9]{2})[0-9]{12})\b"
    ),
    "SSN": re.compile(r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b"),
    "API_KEY": re.compile(
        r"\b(?:sk-[a-zA-Z0-9]{20,}|AIza[0-9A-Za-z-_]{35}|ghp_[a-zA-Z0-9]{36}|aws[_-]?(?:key|token)?[_-]?[a-zA-Z0-9]{16,})\b",
        re.IGNORECASE,
    ),
    "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
    "PHONE": re.compile(
        r"\b(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
    ),
}

# Prompt injection triggers and override tokens
PROMPT_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions?", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous|prior|above)\s+(instructions?|rules?)", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(in\s+developer\s+mode|unrestricted|DAN)", re.IGNORECASE),
    re.compile(r"system\s*override", re.IGNORECASE),
    re.compile(r"reveal\s+(all\s+)?(secret|passwords?|keys?|system\s+prompt)", re.IGNORECASE),
]

# Security Audit Log (in-memory circular buffer with timestamp)
_SECURITY_AUDIT_LOG: list[dict[str, Any]] = []
MAX_AUDIT_LOG_SIZE = 1000


def log_security_event(event_type: str, user_id: int | None = None, details: dict[str, Any] | None = None) -> None:
    """Records a security-sensitive event with timestamp and tenant context."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "user_id": user_id,
        "details": details or {},
    }
    _SECURITY_AUDIT_LOG.append(entry)
    if len(_SECURITY_AUDIT_LOG) > MAX_AUDIT_LOG_SIZE:
        _SECURITY_AUDIT_LOG.pop(0)
    logger.info("SECURITY_EVENT [%s] user=%s details=%s", event_type, user_id, details)


def get_recent_security_events(user_id: int | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """Returns recent security audit events, optionally filtered by user_id."""
    if user_id is None:
        return list(reversed(_SECURITY_AUDIT_LOG[-limit:]))
    filtered = [e for e in _SECURITY_AUDIT_LOG if e.get("user_id") == user_id]
    return list(reversed(filtered[-limit:]))


# ==============================================================================
# 1. PII Redaction & Data Privacy Sanitization
# ==============================================================================

def redact_pii(text: str, mask_types: list[str] | None = None) -> tuple[str, list[dict[str, Any]]]:
    """
    Masks Personally Identifiable Information (PII) like credit cards, SSNs,
    API keys, emails, and phone numbers to safeguard user privacy.

    Returns:
        (sanitized_text: str, detections: list[dict])
    """
    if not text:
        return text, []

    sanitized = text
    detections: list[dict[str, Any]] = []

    types_to_scan = mask_types or list(PII_PATTERNS.keys())
    for pii_type in types_to_scan:
        pattern = PII_PATTERNS.get(pii_type)
        if not pattern:
            continue

        for match in pattern.finditer(sanitized):
            val = match.group(0)
            detections.append({
                "type": pii_type,
                "length": len(val),
            })

        sanitized = pattern.sub(f"[REDACTED-{pii_type}]", sanitized)

    return sanitized, detections


def contains_pii(text: str) -> bool:
    """Returns True if any sensitive PII pattern is matched in the text."""
    if not text:
        return False
    return any(p.search(text) is not None for p in PII_PATTERNS.values())


# ==============================================================================
# 2. Prompt Injection Defense
# ==============================================================================

def detect_prompt_injection(text: str) -> bool:
    """Checks whether the text contains known indirect or direct prompt injection attempts."""
    if not text:
        return False
    return any(p.search(text) is not None for p in PROMPT_INJECTION_PATTERNS)


def sanitize_for_prompt_context(text: str) -> str:
    """
    Sanitizes untrusted document text before embedding it into system prompts.
    Defangs prompt injection phrases and neutralizes bracketed command tokens.
    """
    if not text:
        return ""

    sanitized = text
    # Defang markdown code block injections and system role tags
    sanitized = re.sub(r"```\s*(system|admin|override)", "``` text", sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"<\s*/?\s*(?:system|instruction|prompt)\s*>", "[sanitized-tag]", sanitized, flags=re.IGNORECASE)

    # Neutralize explicit override instructions
    for pattern in PROMPT_INJECTION_PATTERNS:
        sanitized = pattern.sub("[filtered-instruction]", sanitized)

    return sanitized


# ==============================================================================
# 3. Path Traversal & Sandbox Protection
# ==============================================================================

def is_safe_path(base_directory: str, path_to_check: str) -> bool:
    """
    Verifies that `path_to_check` resolves strictly within `base_directory`.
    Guards against directory traversal attacks (e.g., `../../etc/passwd`).
    """
    try:
        resolved_base = os.path.realpath(os.path.abspath(base_directory))
        resolved_target = os.path.realpath(os.path.abspath(path_to_check))
        common = os.path.commonpath([resolved_base, resolved_target])
        return common == resolved_base
    except Exception:
        return False


def get_secure_user_upload_dir(base_upload_folder: str, user_id: int) -> str:
    """Returns the sandboxed, user-isolated upload directory path."""
    user_dir = os.path.join(base_upload_folder, str(user_id))
    if not is_safe_path(base_upload_folder, user_dir):
        raise ValueError(f"Path traversal detected for user_id {user_id}")
    os.makedirs(user_dir, exist_ok=True)
    return user_dir


# ==============================================================================
# 4. Cryptographic File Integrity Verification (SHA-256)
# ==============================================================================

def compute_file_sha256(file_path: str) -> str:
    """Computes the SHA-256 cryptographic digest of a file on disk."""
    if not os.path.exists(file_path):
        return ""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def compute_bytes_sha256(data: bytes) -> str:
    """Computes the SHA-256 cryptographic digest of in-memory bytes."""
    return hashlib.sha256(data).hexdigest()
