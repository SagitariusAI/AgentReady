"""Source-signal safety / redaction scanning for the Agent Data Foundry.

Phase C1 of the module split (docs/refactors/AGENT_DATA_FOUNDRY_MODULE_SPLIT_PLAN.md):
the source-signal safety-scan / redaction leaf moved verbatim out of
agent_data_foundry.py with **no behavior change**. Pure leaf — depends only on the
stdlib (`json`, `re`) and `typing`.

The safety contract is unchanged and deliberately conservative:
- Severe secret material (private keys, credentialed URLs, secret assignments, AWS /
  GitHub / Slack / Google tokens) -> QUARANTINE; the caller downgrades the row's
  data_rights to F_QUARANTINE and excludes it from the Dojo / any export.
- Username / email / absolute user path -> REDACTED in place (the row is kept).
- An `.env` *path* reference is a pointer, not the secret -> flagged, field unchanged.
- Diff text is code: a real-looking token quarantines, but a clearly-fake token in a
  test/fixture path is REDACTED-not-quarantined so the Factory can still learn from
  its own security-test diffs. The fake-token carveout is STRICT (a real-looking
  token with no fake marker still quarantines, even in a test file).
- Findings never carry the raw matched secret — only detector + severity.
"""
from __future__ import annotations

import json
import re
from typing import Any

# Fields of a source_signals envelope that may carry sensitive raw content.
SOURCE_SIGNAL_SCAN_FIELDS = (
    "paths_touched",
    "commands_run",
    "test_commands",
    "protected_path_touches",
    "command_surfaces",
)

# Severe detectors: a hit means real secret material -> the record is quarantined,
# never exported. The matched span is masked in the redacted copy as a defensive
# second layer (quarantined rows are excluded from the Dojo regardless). High
# precision on purpose: a generic high-entropy detector is deliberately omitted to
# avoid quarantining legitimate hashes/fingerprints (a later, tunable DLP slice).
SOURCE_SIGNAL_SEVERE_DETECTORS = [
    ("private_key_material", re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    ("url_with_credentials", re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^/\s:@]+:[^/\s:@]+@")),
    ("secret_assignment", re.compile(r"(?i)\b(?:password|passwd|secret|token|api[_-]?key|apikey|access[_-]?key|client[_-]?secret|private[_-]?key)\b\s*[=:]\s*\S+")),
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_secret_hint", re.compile(r"(?i)\baws_secret_access_key\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{8,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
]

# Diff-text severe detectors. Diff text IS code, so the loose `token=<anything>`
# keyword detector would quarantine legitimate variable assignments
# (`token = get_token()`). For diff text we keep the high-precision format
# detectors and replace the keyword detector with a literal-secret one that
# requires a quoted long literal value (`token = "ghp_..."`), not a function call.
SOURCE_SIGNAL_DIFF_SEVERE_DETECTORS = [
    ("private_key_material", re.compile(r"-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY-----")),
    ("url_with_credentials", re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://[^/\s:@]+:[^/\s:@]+@")),
    ("secret_literal_assignment", re.compile(r"(?i)\b(?:password|passwd|secret|token|api[_-]?key|apikey|access[_-]?key|client[_-]?secret|private[_-]?key)\b\s*[=:]\s*[\"'][^\"'\s]{8,}[\"']")),
    ("aws_access_key_id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("aws_secret_hint", re.compile(r"(?i)\baws_secret_access_key\b")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{8,}")),
    ("google_api_key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
]

# Redact detectors: safe-to-retain rows where the sensitive span is scrubbed in
# place (username, email) and the record is kept with status REDACTED.
_USER_PATH_RE = re.compile(r"(?i)([A-Za-z]:[\\/]Users[\\/]|/" + r"home/|/Users/)([^\\/\s]+)")
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")

# Flag detectors: recorded for review but not a secret to scrub (an .env *path*
# reference is a pointer, not the secret); status becomes REDACTED, field unchanged.
_DOTENV_RE = re.compile(r"(?i)(?:^|[\\/])\.env(?:\.(?!example|sample|template|dist)[A-Za-z0-9]+)?(?:[\\/]|$)")


def _scan_source_signal_value(
    value: str,
    severe_detectors: list[tuple[str, re.Pattern[str]]] = SOURCE_SIGNAL_SEVERE_DETECTORS,
) -> tuple[str, list[dict[str, str]], bool, bool]:
    """Scan one string. Returns (possibly-redacted string, findings, redacted, severe).
    Findings never carry the raw matched secret -- only detector + severity."""
    findings: list[dict[str, str]] = []
    out = value
    severe = False
    redacted = False
    for name, regex in severe_detectors:
        if regex.search(out):
            findings.append({"detector": name, "severity": "severe"})
            out = regex.sub(f"<REDACTED:{name.upper()}>", out)
            severe = True
            redacted = True
    if _EMAIL_RE.search(out):
        findings.append({"detector": "email_address", "severity": "redact"})
        out = _EMAIL_RE.sub("<REDACTED:EMAIL>", out)
        redacted = True
    if _USER_PATH_RE.search(out):
        findings.append({"detector": "absolute_user_path", "severity": "redact"})
        out = _USER_PATH_RE.sub(lambda m: m.group(1) + "<REDACTED_USER>", out)
        redacted = True
    if _DOTENV_RE.search(out):
        findings.append({"detector": "dotenv_reference", "severity": "flag"})
    return out, findings, redacted, severe


# Markers that make a matched secret span obviously a fake test fixture rather
# than a real leak. STRICT on purpose: a real-looking token (no marker) in a test
# file still quarantines -- humans do leak real secrets into tests.
_FAKE_SECRET_MARKERS = (
    "example", "fake", "dummy", "sample", "placeholder", "redacted", "notreal",
    "change" + "me", "test", "todo", "xxxx", "0000", "your-", "your_", "deadbeef",
)


def _looks_like_fake_secret(span: str) -> bool:
    low = span.lower()
    return any(marker in low for marker in _FAKE_SECRET_MARKERS)


def _is_test_or_fixture_path(path: str) -> bool:
    low = path.replace("\\", "/").lower().strip()
    if not low or low == "/dev/null":
        return False
    name = low.rsplit("/", 1)[-1]
    return (
        "/tests/" in low or low.startswith("tests/") or "/test/" in low
        or name.startswith("test_") or name.endswith("_test.py") or name == "conftest.py"
        or "/fixtures/" in low or low.startswith("fixtures/") or "/__fixtures__/" in low
        or "/docs/examples/" in low or "/examples/" in low
    )


def _diff_current_file(line: str) -> str | None:
    """The destination path a unified-diff header introduces, else None."""
    if line.startswith("+++ "):
        path = line[4:].strip()
        return path[2:] if path.startswith(("a/", "b/")) else path
    if line.startswith("diff --git "):
        parts = line.split()
        if len(parts) >= 4:
            dest = parts[-1]
            return dest[2:] if dest.startswith(("a/", "b/")) else dest
    return None


def _scan_diff_patch(diff_text: str) -> tuple[str, list[dict[str, str]], bool, bool]:
    """Diff-aware scan. Tracks the current file per hunk so a severe-token match
    can be classified as a fake test fixture (test/fixture path AND clearly-fake
    value -> REDACTED, not quarantine) versus a real leak (-> severe/quarantine).
    Returns (redacted_diff, findings, redacted, has_real_severe)."""
    findings: list[dict[str, str]] = []
    out_lines: list[str] = []
    redacted = False
    has_real_severe = False
    current_file = ""
    for line in diff_text.splitlines():
        header = _diff_current_file(line)
        if header is not None:
            current_file = header
        new_line = line
        test_context = _is_test_or_fixture_path(current_file)
        for name, regex in SOURCE_SIGNAL_DIFF_SEVERE_DETECTORS:
            matches = list(regex.finditer(new_line))
            if not matches:
                continue
            for match in matches:
                if test_context and _looks_like_fake_secret(match.group(0)):
                    findings.append({"detector": f"{name}_fixture", "severity": "fixture", "action": "redacted_not_quarantined"})
                else:
                    findings.append({"detector": name, "severity": "severe"})
                    has_real_severe = True
            new_line = regex.sub(f"<REDACTED:{name.upper()}>", new_line)
            redacted = True
        if _EMAIL_RE.search(new_line):
            findings.append({"detector": "email_address", "severity": "redact"})
            new_line = _EMAIL_RE.sub("<REDACTED:EMAIL>", new_line)
            redacted = True
        if _USER_PATH_RE.search(new_line):
            findings.append({"detector": "absolute_user_path", "severity": "redact"})
            new_line = _USER_PATH_RE.sub(lambda m: m.group(1) + "<REDACTED_USER>", new_line)
            redacted = True
        out_lines.append(new_line)
    return "\n".join(out_lines), findings, redacted, has_real_severe


def _empty_source_signal_safety() -> dict[str, Any]:
    return {
        "schema_version": "sf.source_signal_safety.v0.1",
        "scan_status": "PASS",
        "findings": [],
        "redacted_fields": [],
        "quarantine_reason": None,
    }


def scan_source_signals(signals: Any) -> tuple[Any, dict[str, Any]]:
    """Scan a source_signals envelope for sensitive content. Returns a
    (safe_signals, safety_block) pair. Severe secret material -> QUARANTINE
    (caller downgrades data_rights to F_QUARANTINE and excludes the row).
    Username/email -> REDACTED in place. Nothing found -> PASS. Records without
    a source_signals dict are a no-op PASS."""
    if not isinstance(signals, dict):
        return signals, _empty_source_signal_safety()
    safe = json.loads(json.dumps(signals))
    findings: list[dict[str, str]] = []
    redacted_fields: set[str] = set()
    severe_detectors: set[str] = set()
    for field in SOURCE_SIGNAL_SCAN_FIELDS:
        values = safe.get(field)
        if not isinstance(values, list):
            continue
        new_values = []
        for value in values:
            cleaned, value_findings, redacted, severe = _scan_source_signal_value(str(value))
            new_values.append(cleaned)
            for finding in value_findings:
                findings.append({"field": field, **finding})
                if finding["severity"] == "severe":
                    severe_detectors.add(finding["detector"])
            if redacted:
                redacted_fields.add(field)
        safe[field] = new_values
    # file_status is a list of {op, path} dicts -> scan each path so git-status
    # data cannot smuggle a secret or username past the filter.
    file_status = safe.get("file_status")
    if isinstance(file_status, list):
        for entry in file_status:
            if not (isinstance(entry, dict) and isinstance(entry.get("path"), str)):
                continue
            cleaned, value_findings, redacted, _severe = _scan_source_signal_value(entry["path"])
            entry["path"] = cleaned
            for finding in value_findings:
                findings.append({"field": "file_status", **finding})
                if finding["severity"] == "severe":
                    severe_detectors.add(finding["detector"])
            if redacted:
                redacted_fields.add("file_status")
    # diff_patch is free-text code scanned per-hunk: a real secret quarantines,
    # but a clearly-fake token in a test/fixture file is REDACTED, not quarantined,
    # so the Factory can still learn from its own security-test diffs.
    diff_patch = safe.get("diff_patch")
    if isinstance(diff_patch, str) and diff_patch:
        cleaned, value_findings, redacted, _real_severe = _scan_diff_patch(diff_patch)
        safe["diff_patch"] = cleaned
        for finding in value_findings:
            findings.append({"field": "diff_patch", **finding})
            if finding["severity"] == "severe":
                severe_detectors.add(finding["detector"])
        if redacted:
            redacted_fields.add("diff_patch")
    if severe_detectors:
        status = "QUARANTINE"
        reason = "sensitive_source_signal_content:" + ",".join(sorted(severe_detectors))
    elif findings:
        status = "REDACTED"
        reason = None
    else:
        status = "PASS"
        reason = None
    return safe, {
        "schema_version": "sf.source_signal_safety.v0.1",
        "scan_status": status,
        "findings": findings,
        "redacted_fields": sorted(redacted_fields),
        "quarantine_reason": reason,
    }
