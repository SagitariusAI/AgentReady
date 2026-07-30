"""Append-only task event stream — port of `Add-AgentEvent` (`bin/agent-coordination-lib.ps1` L223).
One JSONL line per event under `events/<task_id>.jsonl`, with the exact PowerShell record shape."""
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
