"""Task store CRUD — port of `Get-AgentTaskPath` (L204), `Read-AgentTask` (L209), `Write-AgentTask`
(L216), `Get-AgentTasks` (L245). The record schema is whatever task-start writes (see Phase 1G); these
are the generic primitives every coordination command uses."""
from __future__ import annotations

from pathlib import Path

from agent_coordination.common import new_task_id, now_stamp, read_json, slug, write_json
from agent_coordination.store import ensure_state, state_dir
from agent_workflow_lanes import stamp_workflow_lane

# default "active" statuses (Get-AgentTasks default, L248)
ACTIVE_STATUSES = ("open", "claimed", "in_progress", "handoff", "review")


def task_path(repo, task_id: str) -> Path:
    return state_dir(repo, "tasks") / f"{task_id}.json"


def read_task(repo, task_id: str) -> dict:
    path = task_path(repo, task_id)
    if not path.exists():
        raise FileNotFoundError(f"Task not found: {task_id}")  # mirrors PS `throw "Task not found"`
    return read_json(path, default={})


def write_task(repo, task: dict) -> Path:
    """Set updated_at and persist. Mirrors Write-AgentTask (L216)."""
    stamped = stamp_workflow_lane(task)
    stamped["updated_at"] = now_stamp()
    task.clear()
    task.update(stamped)
    path = task_path(repo, task["id"])
    return write_json(path, task)


def get_tasks(repo=None, status=ACTIVE_STATUSES) -> list[dict]:
    """All task records, optionally filtered by status. Mirrors Get-AgentTasks (L245)."""
    state = ensure_state(repo)
    tasks = []
    tasks_dir = state / "tasks"
    if not tasks_dir.exists():
        return tasks
    for path in sorted(tasks_dir.glob("*.json")):
        record = read_json(path, default=None)
        if record and (not status or record.get("status") in status):
            tasks.append(record)
    return tasks


__all__ = ["task_path", "read_task", "write_task", "get_tasks", "new_task_id", "slug", "ACTIVE_STATUSES"]
