# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Fail-closed privacy and persistence guard for public AgentReady releases."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

PYTHON_HEADER = (
    "# Copyright (c) 2026 Sagittarius AI\n"
    "# Project Owner: Alex Burca\n"
    "# SPDX-License-Identifier: Apache-2.0\n"
)

IGNORED_ROOTS = {
    ".git",
    ".venv",
    ".agent-reports",
    ".agent-state",
    ".agentready",
    ".agent_graph",
    ".factory_capture",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".serena",
    "build",
    "dist",
    "htmlcov",
}
FORBIDDEN_SEGMENTS = {
    ".agent-reports",
    ".agent-state",
    ".agentready",
    ".agent_graph",
    ".factory_capture",
    ".serena",
    "coordination",
    "credentials",
    "data",
    "datasets",
    "logs",
    "reports",
    "runtime",
    "secrets",
    "state",
    "tokens",
    "worktrees",
}
FORBIDDEN_SUFFIXES = {
    ".age",
    ".arrow",
    ".csv",
    ".db",
    ".duckdb",
    ".env",
    ".faiss",
    ".feather",
    ".har",
    ".index",
    ".journal",
    ".jsonl",
    ".kdbx",
    ".key",
    ".log",
    ".parquet",
    ".p12",
    ".pcap",
    ".pem",
    ".pfx",
    ".shm",
    ".sql",
    ".sqlite",
    ".sqlite3",
    ".tsv",
    ".wal",
}
TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("production_path", re.compile(r"(?i)D:[\\/]+" r"AgentReady(?:[\\/]+|$)")),
    ("user_profile", re.compile(r"(?i)[A-Z]:[\\/]+Users[\\/]+(?!sample-user(?:[\\/]+|$))[^\\/\s]+")),
    ("unix_home", re.compile(r"(?i)/" + r"home/(?!user(?:/|$))[^/\s]+")),
    ("private_ipv4", re.compile(
        r"(?<![\d.])(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|"
        r"172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?![\d.])"
    )),
    ("embedded_uri_credential", re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^/\s:@]+:[^@\s/]+@")),
    ("private_key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("github_token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("known_default_secret", re.compile(
        r"(?i)\b(?:" + "agentready" + r"-local|change" + r"-me|change" + r"me)\b"
    )),
    ("internal_project", re.compile(
        r"(?i)\b(?:"
        + "Sovereign" + r"[ _.-]*" + "Forge"
        + "|Company" + r"[ _.-]*" + "OS"
        + "|Open" + r"[ _.-]*" + "Jarvis"
        + r")\b"
    )),
    ("private_asset", re.compile(
        r"(?i)\b(?:"
        + "Cer" + "berus"
        + "|Logos" + "One"
        + "|Sovereign" + r"[ _.-]*" + "Studio"
        + "|Data" + r"[ _.-]*" + "Forge"
        + r")\b"
    )),
    ("restricted_language", re.compile(
        r"(?i)\b(?:"
        + "internal" + r"[-_ ]*only"
        + "|pro" + "prietary"
        + "|never" + r"\s+" + "externalized"
        + "|" + "found" + "er" + r"[-_ ]*" + "mandated"
        + r")\b"
    )),
    ("local_username", re.compile(r"(?i)\b" + "alex" + r"b\b")),
)
EMAIL_PATTERN = re.compile(r"(?i)\b[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})\b")
RESERVED_EMAIL_DOMAINS = {"example.com", "example.net", "example.org", "example.invalid"}
DECLARATIVE_RUNTIME_PATHS = {".agentready/ci.json"}


@dataclass(frozen=True)
class Finding:
    category: str
    path: str
    detail: str


def _safe_member(name: str) -> str | None:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts or re.match(r"^[A-Za-z]:", normalized):
        return None
    return path.as_posix()


def _path_findings(path: str) -> list[Finding]:
    normalized = _safe_member(path)
    if normalized is None:
        return [Finding("unsafe_path", path, "absolute, drive-qualified, or traversal path")]
    parts = {part.lower() for part in PurePosixPath(normalized).parts}
    findings: list[Finding] = []
    blocked = sorted(parts & FORBIDDEN_SEGMENTS)
    if blocked and normalized.lower() not in DECLARATIVE_RUNTIME_PATHS:
        findings.append(Finding("runtime_path", normalized, ", ".join(blocked)))
    lower = normalized.lower()
    suffixes = Path(lower).suffixes
    if any(suffix in FORBIDDEN_SUFFIXES for suffix in suffixes):
        findings.append(Finding("persistence_payload", normalized, "".join(suffixes)))
    if lower.endswith((".zip", ".7z", ".tar", ".tar.gz", ".tgz")):
        findings.append(Finding("nested_archive", normalized, "archives must be generated, never nested"))
    return findings


def _text_findings(path: str, data: bytes) -> list[Finding]:
    if b"\x00" in data:
        return []
    text = data.decode("utf-8", errors="replace")
    findings: list[Finding] = []
    for category, pattern in TEXT_PATTERNS:
        match = pattern.search(text)
        if match:
            detail = match.group(0)
            if category in {"github_token", "embedded_uri_credential", "private_key", "known_default_secret"}:
                detail = "<redacted>"
            findings.append(Finding(category, path, detail[:160]))
    for match in EMAIL_PATTERN.finditer(text):
        domain = match.group(1).lower()
        if domain not in RESERVED_EMAIL_DOMAINS and not domain.endswith(".test"):
            findings.append(Finding("email_address", path, "<redacted>"))
            break
    return findings


def _python_header_findings(path: str, data: bytes) -> list[Finding]:
    if not path.lower().endswith(".py"):
        return []
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    lines = text.splitlines(keepends=True)
    offset = 0
    if lines and lines[0].startswith("#!"):
        offset = 1
    if offset < len(lines) and re.match(r"^#.*coding[:=]", lines[offset]):
        offset += 1
    prologue = "".join(lines[offset:offset + 3])
    if prologue != PYTHON_HEADER:
        return [Finding("python_header", path, "missing or non-canonical ownership/SPDX header")]
    return []


def _source_files(repo: Path) -> list[Path]:
    proc = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        check=False,
        capture_output=True,
    )
    if proc.returncode == 0:
        names = [item for item in proc.stdout.decode("utf-8", errors="surrogateescape").split("\0") if item]
        return sorted((repo / name for name in names if (repo / name).is_file()), key=lambda p: p.as_posix())
    return sorted(
        (
            path
            for path in repo.rglob("*")
            if path.is_file() and not ({part.lower() for part in path.relative_to(repo).parts} & IGNORED_ROOTS)
        ),
        key=lambda p: p.as_posix(),
    )


def scan_source(repo: Path) -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    files = _source_files(repo)
    for file_path in files:
        relative = file_path.relative_to(repo).as_posix()
        findings.extend(_path_findings(relative))
        data = file_path.read_bytes()
        findings.extend(_text_findings(relative, data))
        findings.extend(_python_header_findings(relative, data))
    return findings, len(files)


def scan_archive(archive: Path) -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    count = 0
    with zipfile.ZipFile(archive) as bundle:
        bad = bundle.testzip()
        if bad:
            findings.append(Finding("archive_crc", bad, "CRC failure"))
        for info in bundle.infolist():
            if info.is_dir():
                continue
            count += 1
            findings.extend(_path_findings(info.filename))
            data = bundle.read(info)
            findings.extend(_text_findings(info.filename, data))
            findings.extend(_python_header_findings(info.filename, data))
    return findings, count


def git_head(repo: Path) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    head = result.stdout.strip()
    return head if result.returncode == 0 and head else None


def write_report(repo: Path, payload: dict[str, object], out_dir: Path | None = None) -> Path:
    root = out_dir or repo / ".agent-reports" / "publication-guard"
    root.mkdir(parents=True, exist_ok=True)
    latest = root / "latest.json"
    latest.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return latest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reject private data and runtime state from public releases.")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--out-dir", type=Path)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    if args.archive:
        findings, file_count = scan_archive(args.archive.resolve())
        target = str(args.archive.resolve())
    else:
        findings, file_count = scan_source(repo)
        target = str(repo)
    payload = {
        "schema": "agentready.publication_guard.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "target": target,
        "git_head": git_head(repo),
        "file_count": file_count,
        "finding_count": len(findings),
        "overall": "PASS" if not findings else "FAIL",
        "findings": [asdict(item) for item in findings],
    }
    report = write_report(repo, payload, args.out_dir)
    print(f"AgentReady publication guard: {payload['overall']} ({len(findings)} findings) {report}")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
