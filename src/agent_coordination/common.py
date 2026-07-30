# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Small self-contained helpers for the coordination foundation."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

_SLUG_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def now_stamp() -> str:
    """Return a local ISO timestamp with second precision and no offset."""
    return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def task_stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def slug(text: str) -> str:
    """Port of ConvertTo-AgentSlug (L161): lowercase, non-alnum -> '-', trim, cap at 48."""
    s = _SLUG_NON_ALNUM.sub("-", (text or "").lower()).strip("-")
    if not s:
        s = "task"
    if len(s) > 48:
        s = s[:48].rstrip("-")
    return s


def new_task_id(title: str) -> str:
    """Port of New-AgentTaskId (L169): `<yyyyMMdd-HHmmss>-<slug>`."""
    return f"{task_stamp()}-{slug(title)}"


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
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(obj, ensure_ascii=True) + "\n")


def iter_jsonl(path: Path) -> Iterator[dict]:
    path = Path(path)
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                yield json.loads(line)
            except ValueError:
                continue
