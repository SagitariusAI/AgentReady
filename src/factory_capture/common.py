"""Pure stdlib helpers for the Factory Capture Runtime: timestamps, ids, hashing, JSON/JSONL io.

No third-party dependencies; no imports from other factory_capture modules (this is a leaf)."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def now_iso() -> str:
    """UTC timestamp, ISO-8601 with offset (e.g. 2026-06-17T12:00:00.123456+00:00)."""
    return datetime.now(timezone.utc).isoformat()


def gen_event_id() -> str:
    """Time-sortable, collision-resistant event id: <compact-utc>-<8 hex>."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    return f"{stamp}-{uuid.uuid4().hex[:8]}"


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8", errors="replace")).hexdigest()


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(path: Path, obj: Any) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=True), encoding="utf-8")
    return path


def append_jsonl(path: Path, obj: Any) -> None:
    """Append one JSON record as a line. Creates parent dirs. Append-only by design."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, ensure_ascii=True) + "\n")


def iter_jsonl(path: Path) -> Iterator[dict]:
    """Yield each JSON record from a JSONL file; skips blank/corrupt lines without failing."""
    path = Path(path)
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def read_jsonl(path: Path) -> list[dict]:
    return list(iter_jsonl(path))
