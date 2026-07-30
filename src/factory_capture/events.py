# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Capture-event schema + append/index/query. JSONL is the source of truth; SQLite mirrors the
queryable columns. Append is the only write path (append-only receipts)."""
from __future__ import annotations

import json
import sqlite3
from typing import Iterator

from factory_capture.common import append_jsonl, gen_event_id, iter_jsonl, now_iso
from factory_capture.store import Store

CAPTURE_EVENT_SCHEMA = "sf.capture_event.v0.1"
EVENT_TYPES = ("command_run", "git_hook", "session_start", "session_end", "manual_note", "summary")


def new_event(event_type: str, **fields) -> dict:
    """A schema-complete event with safe defaults; callers override via fields."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event_type: {event_type!r} (allowed: {EVENT_TYPES})")
    event = {
        "schema": CAPTURE_EVENT_SCHEMA,
        "event_id": gen_event_id(),
        "event_type": event_type,
        "timestamp_start": now_iso(),
        "timestamp_end": now_iso(),
        "duration_ms": 0,
        "cwd": "",
        "repo_root": "",
        "command": None,
        "exit_code": None,
        "git_before": None,
        "git_after": None,
        "stdout_log": None,
        "stderr_log": None,
        "stdout_sha256": None,
        "stderr_sha256": None,
        "artifacts": [],
        "redaction": {"applied": False, "findings": []},
        "status": "success",
    }
    event.update(fields)
    return event


def _index_event(store: Store, event: dict) -> None:
    """Mirror the event into the SQLite index (best-effort; JSONL remains the truth)."""
    git_after = event.get("git_after") or {}
    command = event.get("command")
    try:
        con = store.connect()
        con.execute(
            "insert or replace into events(event_id, event_type, timestamp_start, timestamp_end, "
            "duration_ms, exit_code, status, command, repo_root, commit_after, dirty_after) "
            "values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event["event_id"], event["event_type"], event.get("timestamp_start"),
                event.get("timestamp_end"), event.get("duration_ms"), event.get("exit_code"),
                event.get("status"), json.dumps(command) if command is not None else None,
                event.get("repo_root"), git_after.get("commit", ""), int(bool(git_after.get("dirty"))),
            ),
        )
        con.commit()
        con.close()
    except sqlite3.Error:
        # the JSONL append already succeeded; the index is a cache, not the record of truth
        return


def append_event(store: Store, event: dict) -> dict:
    """Append a new event, or accept an identical replay without duplication."""
    store.ensure_dirs()
    event_id = str(event.get("event_id") or "")
    if not event_id:
        raise ValueError("capture event requires event_id")
    for existing in iter_events(store):
        if str(existing.get("event_id") or "") != event_id:
            continue
        if existing != event:
            raise ValueError(f"capture event_id replay conflict: {event_id}")
        _index_event(store, existing)
        return existing
    append_jsonl(store.events_path, event)
    _index_event(store, event)
    return event


def iter_events(store: Store) -> Iterator[dict]:
    yield from iter_jsonl(store.events_path)


def all_events(store: Store) -> list[dict]:
    return list(iter_events(store))


def count_events(store: Store) -> int:
    return sum(1 for _ in iter_events(store))


def last_events(store: Store, n: int = 10) -> list[dict]:
    events = all_events(store)
    return events[-n:] if n > 0 else events
