# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Path locks for concurrent-work claims — port of `Set-AgentLocks` (L360-378) and `Remove-AgentLocks`
(L380-390). One lock file per claimed path under `locks/<sha256(path)[:16]>.json`."""
from __future__ import annotations

import hashlib

from agent_coordination.common import now_stamp, read_json, write_json
from agent_coordination.paths import to_path_list
from agent_coordination.store import ensure_state


def lock_hash(normalized_path: str) -> str:
    """sha256 of the normalized path, first 16 hex (PS L365-368)."""
    return hashlib.sha256(normalized_path.encode("utf-8")).hexdigest()[:16]


def set_locks(repo, task: dict) -> list[str]:
    """Write a lock file per claimed path. Returns the lock hashes written."""
    state = ensure_state(repo)
    lock_root = state / "locks"
    written = []
    for normalized in to_path_list(task.get("paths")):
        h = lock_hash(normalized)
        write_json(lock_root / f"{h}.json", {
            "task_id": task.get("id"),
            "agent": task.get("agent"),
            "path": normalized,
            "status": task.get("status"),
            "updated_at": now_stamp(),
        })
        written.append(h)
    return written


def remove_locks(repo, task_id: str) -> int:
    """Remove every lock file owned by task_id. Returns the count removed."""
    state = ensure_state(repo)
    lock_root = state / "locks"
    removed = 0
    if not lock_root.exists():
        return 0
    for path in sorted(lock_root.glob("*.json")):
        lock = read_json(path, default=None)
        if lock and lock.get("task_id") == task_id:
            path.unlink()
            removed += 1
    return removed
