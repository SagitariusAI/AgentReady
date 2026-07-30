# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Local, deterministic secret redaction for captured logs and event payloads.

redact_text returns the redacted string plus findings (kind + count only — never the secret).
Stored logs and event JSON are redacted before they are written; the live terminal stream is left
raw (it is the owner's own screen, not stored). Intentionally conservative, not exhaustive: the
goal is "don't persist obvious secrets raw", not a full DLP engine. No imports from siblings (leaf)."""
from __future__ import annotations

import re

# (kind, compiled pattern, keep-prefix-template). keep_prefix is applied via match.expand for
# key=value secrets so the key name survives and only the value is replaced; None replaces the
# whole match. Order matters: specific/structured patterns run before generic ones.
_PATTERNS: list[tuple[str, re.Pattern, str | None]] = [
    ("private_key", re.compile(r"-----BEGIN[A-Z ]*PRIVATE KEY-----[\s\S]*?-----END[A-Z ]*PRIVATE KEY-----"), None),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}"), None),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}"), None),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b"), None),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9]{20,}"), None),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), None),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}"), None),
    ("env_secret", re.compile(
        r"(?im)([A-Z0-9_]*(?:KEY|SECRET|TOKEN|PASSWORD|PASSWD|PWD|CREDENTIAL)[A-Z0-9_]*\s*[=:]\s*)"
        r"([^\s'\"]{6,})"), r"\1"),
    ("email", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), None),
]


def redact_text(text: str) -> tuple[str, list[dict]]:
    """Return (redacted_text, findings). findings = [{"kind": str, "count": int}, ...]."""
    if not text:
        return text, []
    findings: list[dict] = []
    for kind, pattern, keep in _PATTERNS:
        counter = {"n": 0}

        def _replace(match: re.Match, kind: str = kind, keep: str | None = keep, counter=counter) -> str:
            counter["n"] += 1
            prefix = match.expand(keep) if keep else ""
            return f"{prefix}[REDACTED:{kind}]"

        text = pattern.sub(_replace, text)
        if counter["n"]:
            findings.append({"kind": kind, "count": counter["n"]})
    return text, findings


def redaction_block(*texts: str) -> dict:
    """Aggregate findings across several texts into the event ``redaction`` field."""
    merged: dict[str, int] = {}
    for text in texts:
        _, findings = redact_text(text or "")
        for finding in findings:
            merged[finding["kind"]] = merged.get(finding["kind"], 0) + finding["count"]
    findings = [{"kind": k, "count": v} for k, v in sorted(merged.items())]
    return {"applied": bool(findings), "findings": findings}
