from __future__ import annotations

import re
import subprocess

import pytest

import agent_runtime_paths
from agent_coordination import common, events, tasks


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_runtime_paths, "COORDINATION_ROOT", tmp_path / "coordination")
    r = tmp_path / "proj"
    r.mkdir()
    subprocess.run(["git", "init"], cwd=str(r), capture_output=True, check=True)
    return r


def _task(**over) -> dict:
    base = {"id": "t1", "title": "demo", "status": "open", "agent": "claude",
            "summary": "x" * 25, "paths": ["src/a.py"]}
    base.update(over)
    return base


def test_slug_and_new_task_id():
    assert common.slug("Fix the Thing!! Now") == "fix-the-thing-now"
    assert common.slug("") == "task"
    tid = common.new_task_id("Fix X")
    assert re.match(r"^\d{8}-\d{6}-fix-x$", tid)


def test_write_then_read_task_roundtrip_sets_updated_at(repo):
    tasks.write_task(repo, _task())
    got = tasks.read_task(repo, "t1")
    assert got["title"] == "demo" and got["status"] == "open"
    assert "updated_at" in got and re.match(r"\d{4}-\d{2}-\d{2}T", got["updated_at"])


def test_read_missing_task_raises(repo):
    with pytest.raises(FileNotFoundError):
        tasks.read_task(repo, "nope")


def test_get_tasks_filters_by_status(repo):
    tasks.write_task(repo, _task(id="a", status="open"))
    tasks.write_task(repo, _task(id="b", status="complete"))
    tasks.write_task(repo, _task(id="c", status="in_progress"))
    active_ids = {t["id"] for t in tasks.get_tasks(repo)}
    assert active_ids == {"a", "c"}  # 'complete' is not an active status
    assert {t["id"] for t in tasks.get_tasks(repo, status=("complete",))} == {"b"}
    assert {t["id"] for t in tasks.get_tasks(repo, status=())} == {"a", "b", "c"}  # no filter


def test_add_event_appends_jsonl_with_shape(repo):
    events.add_event(repo, "t1", "claim", agent="claude", message="started", data={"k": 1})
    events.add_event(repo, "t1", "handoff", agent="claude")
    state = agent_runtime_paths.state_root(repo)
    rows = list(common.iter_jsonl(state / "events" / "t1.jsonl"))
    assert len(rows) == 2
    assert rows[0]["type"] == "claim" and rows[0]["agent"] == "claude" and rows[0]["data"] == {"k": 1}
    assert set(rows[0]) == {"ts", "task_id", "type", "agent", "message", "data"}
