# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Public support for events."""
from __future__ import annotations

from agent_coordination.common import append_jsonl, now_stamp
from agent_coordination.store import ensure_state


def add_event(repo, task_id: str, event_type: str, agent: str = "", message: str = "",
              data: dict | None = None) -> dict:
    """Append a coordination event. Shape: {ts, task_id, type, agent, message, data} (PS L234-241)."""
    state = ensure_state(repo)
    event = {
        "ts": now_stamp(),
        "task_id": task_id,
        "type": event_type,
        "agent": agent,
        "message": message,
        "data": data or {},
    }
    append_jsonl(state / "events" / f"{task_id}.jsonl", event)
    return event
