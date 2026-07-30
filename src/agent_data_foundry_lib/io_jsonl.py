# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Pure IO / JSONL / report helpers for the Agent Data Foundry."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, overload


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def rel(root: Path, path: Path) -> str:
    return str(path.resolve(strict=False).relative_to(root.resolve(strict=False)))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@overload
def read_json(path: Path) -> dict[str, Any] | None: ...


@overload
def read_json(path: Path, *, expected_type: type[list]) -> list[Any] | None: ...


def read_json(path: Path, *, expected_type: type[dict] | type[list] = dict) -> dict[str, Any] | list[Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, expected_type) else None


def read_json_value(path: Path) -> object:
    """Read any JSON root shape for import surfaces that explicitly validate it."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def as_dict(value: object) -> dict[str, Any]:
    """Return a JSON object or an empty object for absent/wrong-shaped input."""
    return value if isinstance(value, dict) else {}


def as_list(value: object) -> list[Any]:
    """Return a JSON array or an empty array for absent/wrong-shaped input."""
    return value if isinstance(value, list) else []


def _jsonl_dumps(row: dict[str, Any]) -> str:
    """Serialize one JSONL row, escaping the Unicode line separators U+2028/U+2029
    so they cannot become literal line breaks that split a row on read (str
    .splitlines() treats them as newlines). json.loads reads the escaped form
    back to the original character, so the round-trip is lossless."""
    return json.dumps(row, ensure_ascii=False, sort_keys=True).replace(chr(0x2028), "\\u2028").replace(chr(0x2029), "\\u2029")


def read_json_from_line(line: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(line)
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    # Split on "\n" only (read_text normalized \r\n -> \n); splitlines() would also
    # split on U+2028/U+2029 and silently drop rows.
    for line in path.read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        payload = read_json_from_line(line)
        if payload:
            rows.append(payload)
    return rows


def jsonl_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    # Split on "\n" only (read_text already normalized \r\n -> \n); do NOT use
    # splitlines(), which also splits on U+2028/U+2029 and miscounts.
    return sum(1 for line in path.read_text(encoding="utf-8").split("\n") if line.strip())


def append_jsonl_rows(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(_jsonl_dumps(row) + "\n")


def append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(_jsonl_dumps(row) + "\n")
