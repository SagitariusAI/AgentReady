# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Coordination handoff behavior: lane release + handoff-document render (Python engine)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import agent_runtime_paths
from agent_coordination import cli
from agent_coordination import paths as _paths


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    work = tmp_path / "repo"
    work.mkdir()
    subprocess.run(["git", "init"], cwd=str(work), capture_output=True, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=str(work),
                   capture_output=True, check=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(agent_runtime_paths, "COORDINATION_ROOT", home / "coordination")
    monkeypatch.setattr(agent_runtime_paths, "WORKTREE_ROOT", home / "worktrees")
    workstate = home / "src" / "agent_workstate.py"
    workstate.parent.mkdir(parents=True)
    workstate.write_text("raise SystemExit(0)\n", encoding="utf-8")
    monkeypatch.setattr(cli, "AGENTREADY_HOME", home)
    return work


def _store(repo: Path) -> Path:
    return agent_runtime_paths.state_root(repo)


def _only_task(repo: Path) -> dict:
    files = list((_store(repo) / "tasks").glob("*.json"))
    assert len(files) == 1, files
    return json.loads(files[0].read_text(encoding="utf-8"))


def _start(repo: Path) -> str:
    assert cli.main(["task-start", "--repo", str(repo), "--title", "Lane release scenario task",
                     "--agent", "claude", "--summary", "Scenario task to verify handoff lane release.",
                     "--paths", "calc.py", "--skip-awareness"]) == 0
    task_id = _only_task(repo)["id"]
    assert cli.main([
        "task-memory", "--repo", str(repo), "--task-id", task_id, "--agent", "claude",
        "--kind", "graph_query", "--query", "handoff lane release",
        "--evidence", "factory-memory-graph query returned coordination doctrine",
    ]) == 0
    assert cli.main([
        "task-memory", "--repo", str(repo), "--task-id", task_id, "--agent", "claude",
        "--kind", "memory_read", "--store", "shared-memory",
        "--memory-name", "global/factory-doctrine-and-protocols",
        "--evidence", "memory read completed before task action",
    ]) == 0
    return task_id


def _handoff(repo: Path, task_id: str, status: str, **kw) -> int:
    args = ["task-handoff", "--repo", str(repo), "--task-id", task_id, "--agent", "claude",
            "--status", status, "--operator", kw.get("operator", "sample-operator"),
            "--summary", kw.get("summary", "Scenario handoff with interpreted evidence and state."),
            "--evidence", kw.get("evidence", "agent-ci-local: PASS (scenario); no regressions observed."),
            "--next", kw.get("next", "none; scenario complete.")]
    return cli.main(args)


def _lock_count(repo: Path, task_id: str) -> int:
    lock_dir = _store(repo) / "locks"
    n = 0
    for f in lock_dir.glob("*.json"):
        try:
            if json.loads(f.read_text(encoding="utf-8")).get("task_id") == task_id:
                n += 1
        except (OSError, json.JSONDecodeError):
            pass
    return n


def test_complete_handoff_releases_lane(repo):
    # A finished slice frees its lane: terminal status, no conflict on re-claim, locks dropped.
    task_id = _start(repo)
    assert _handoff(repo, task_id, "complete") == 0
    assert _only_task(repo)["status"] == "completed"
    assert _paths.path_conflicts(repo, ["calc.py"]) == []
    assert _lock_count(repo, task_id) == 0


def test_complete_handoff_refuses_when_workstate_gate_is_missing(repo, monkeypatch):
    task_id = _start(repo)
    monkeypatch.setattr(cli, "AGENTREADY_HOME", repo / "missing-agentready-home")
    assert _handoff(repo, task_id, "complete") == 4
    assert _only_task(repo)["status"] == "claimed"
    assert _lock_count(repo, task_id) >= 1


@pytest.mark.parametrize("status", ["wip", "blocked"])
def test_incomplete_handoff_keeps_lane(repo, status):
    # An unfinished slice keeps protecting its lane for whoever resumes it.
    task_id = _start(repo)
    assert _handoff(repo, task_id, status) == 0
    assert _only_task(repo)["status"] == "handoff"
    assert len(_paths.path_conflicts(repo, ["calc.py"])) >= 1
    assert _lock_count(repo, task_id) >= 1


def test_handoff_document_render(repo):

    # author + operator + interpreted evidence (separated from report pointers, no no-summary placeholder),
    # and the task record stores the evidence as test_summary.
    task_id = _start(repo)
    evidence = "FAST gate: PASS at abc123. Full sweep: PASS at def456; interpreted, not a pointer."
    assert _handoff(repo, task_id, "complete", operator="sample-operator", evidence=evidence) == 0

    md_files = list((_store(repo) / "handoffs").glob("*.md"))
    assert len(md_files) == 1, md_files
    md = md_files[0].read_text(encoding="utf-8")
    assert "- Agent: claude" in md
    assert "- Operator: sample-operator" in md
    assert evidence in md
    assert "## Report Pointers" in md
    assert "No explicit test/evidence summary provided" not in md  # evidence given -> no placeholder
    assert "No test summary provided" not in md  # the old placeholder must never resurface
    assert _only_task(repo)["test_summary"] == evidence
