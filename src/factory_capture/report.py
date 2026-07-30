# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Read-only views over the store: `status` (current snapshot) and `tail` (recent events)."""
from __future__ import annotations

from factory_capture.events import count_events, last_events
from factory_capture.gitstate import capture_git_state, find_repo_root
from factory_capture.hooks import hooks_state
from factory_capture.store import Store


def status(store: Store) -> dict:
    repo_root = find_repo_root(store.root.parent)
    git = capture_git_state(repo_root)
    events = last_events(store, 1)
    last = events[-1] if events else None
    last_command = None
    for event in reversed(last_events(store, 0)):
        if event.get("event_type") == "command_run":
            last_command = event
            break
    return {
        "data_root": str(store.root),
        "initialized": store.exists(),
        "repo_root": str(repo_root),
        "branch": git.get("branch", ""),
        "commit": git.get("commit", "")[:12],
        "dirty": git.get("dirty", False),
        "event_count": count_events(store),
        "last_event": None if last is None else {
            "event_id": last.get("event_id"), "event_type": last.get("event_type"),
            "status": last.get("status"), "timestamp_end": last.get("timestamp_end"),
        },
        "last_command": None if last_command is None else {
            "command": last_command.get("command"), "exit_code": last_command.get("exit_code"),
            "status": last_command.get("status"),
        },
        "hooks": hooks_state(repo_root),
    }


def render_status(snap: dict) -> str:
    hooks = ", ".join(f"{k}={'on' if v else 'off'}" for k, v in snap["hooks"].items())
    last = snap["last_event"]
    last_line = "(none)" if not last else f"{last['event_type']} [{last['status']}] {last['timestamp_end']}"
    cmd = snap["last_command"]
    cmd_line = "(none)" if not cmd else f"{' '.join(cmd['command'] or [])} -> exit {cmd['exit_code']} ({cmd['status']})"
    return "\n".join([
        "# Factory Capture Status",
        f"- data root : {snap['data_root']}",
        f"- initialized: {snap['initialized']}",
        f"- repo root : {snap['repo_root']}",
        f"- git       : {snap['branch']}@{snap['commit']} dirty={snap['dirty']}",
        f"- events    : {snap['event_count']}",
        f"- last event: {last_line}",
        f"- last cmd  : {cmd_line}",
        f"- hooks     : {hooks}",
    ]) + "\n"


def render_tail(events: list[dict]) -> str:
    if not events:
        return "(no events)\n"
    rows = []
    for event in events:
        when = (event.get("timestamp_end") or "")[:19]
        kind = event.get("event_type", "?")
        status = event.get("status", "?")
        detail = " ".join(event.get("command") or []) if event.get("event_type") == "command_run" else (
            event.get("text") or event.get("event_id", ""))
        rows.append(f"{when}  {kind:<12} [{status:<7}] {detail}")
    return "\n".join(rows) + "\n"
