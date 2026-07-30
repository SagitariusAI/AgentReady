# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Public support for test agent coordination cli."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import agent_runtime_paths
from agent_coordination import cli


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    """A fresh git repo with the coordination store + adapter home redirected under tmp."""
    work = tmp_path / "repo"
    work.mkdir()
    subprocess.run(["git", "init"], cwd=str(work), capture_output=True, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=str(work),
                   capture_output=True, check=False)
    home = tmp_path / "home"
    home.mkdir()
    workstate = home / "src" / "agent_workstate.py"
    workstate.parent.mkdir(parents=True)
    workstate.write_text("raise SystemExit(0)\n", encoding="utf-8")
    monkeypatch.setattr(agent_runtime_paths, "COORDINATION_ROOT", home / "coordination")
    monkeypatch.setattr(agent_runtime_paths, "WORKTREE_ROOT", home / "worktrees")
    monkeypatch.setattr(cli, "AGENTREADY_HOME", home)
    return work


def _store(repo: Path) -> Path:
    return agent_runtime_paths.state_root(repo)


def _only_task(repo: Path) -> dict:
    files = list((_store(repo) / "tasks").glob("*.json"))
    assert len(files) == 1, files
    return json.loads(files[0].read_text(encoding="utf-8"))


def _start(repo: Path, **kw) -> int:
    args = ["task-start", "--repo", str(repo),
            "--title", kw.get("title", "Coordination cli unit lane check"),
            "--agent", kw.get("agent", "claude"),
            "--summary", kw.get("summary", "exercise the coordination cli unit behavior end to end"),
            "--paths", kw.get("paths", "src/unit_a.py"), "--skip-awareness"]
    if kw.get("workflow_lane"):
        args.extend(["--workflow-lane", kw["workflow_lane"]])
    if kw.get("force"):
        args.append("--force")
    return cli.main(args)


def test_coordination_init(repo):
    assert cli.main(["coordination-init", "--repo", str(repo)]) == 0
    assert (_store(repo) / "tasks").is_dir()


def test_task_start_happy(repo):
    assert _start(repo) == 0
    task = _only_task(repo)
    assert task["status"] == "claimed"
    assert task["agent"] == "claude"
    assert task["paths"] == ["src/unit_a.py"]
    assert task["intent_summary"] == "exercise the coordination cli unit behavior end to end"
    assert task["workflow_lane"] == "business"
    assert task["memory_compliance"]["required"] is True
    assert task["memory_compliance"]["receipts"] == []
    events = (_store(repo) / "events" / f"{task['id']}.jsonl").read_text(encoding="utf-8")
    assert '"type": "task_started"' in events


def test_task_start_records_explicit_research_lane(repo):
    assert _start(repo, workflow_lane="research") == 0
    task = _only_task(repo)
    assert task["workflow_lane"] == "research"
    assert task["workflow_lane_source"] == "explicit"


def test_handoff_does_not_mutate_original_intent_summary(repo):
    assert _start(repo, summary="original declared implementation intent") == 0
    task_id = _only_task(repo)["id"]

    assert cli.main([
        "task-handoff", "--repo", str(repo), "--task-id", task_id, "--agent", "claude",
        "--summary", "outcome summary changed after implementation and verification",
        "--evidence", "unit evidence confirms the immutable intent behavior",
        "--next", "review the completed evidence", "--status", "wip",
    ]) == 0

    task = _only_task(repo)
    assert task["summary"].startswith("outcome summary changed")
    assert task["intent_summary"] == "original declared implementation intent"


def test_task_start_weak_quality_exit3(repo):
    assert cli.main(["task-start", "--repo", str(repo), "--title", "short",
                     "--agent", "claude", "--summary", "tiny", "--skip-awareness"]) == 3


def test_task_start_conflict_exit2(repo):
    assert _start(repo) == 0
    assert _start(repo, title="Second overlapping lane on purpose",
                  summary="overlapping claim on the same path deliberately") == 2


def test_task_start_file_as_repo_clean_exit2(repo, tmp_path, capsys):
    """regression-path-misparse: a file path leaking into --repo must
    exit cleanly (code 2) with a clear message — NOT a traceback — and create no task record."""
    leaked = tmp_path / "stage_forge_deploy_tarball.sh"
    leaked.write_text("echo x", encoding="utf-8")
    rc = cli.main(["task-start", "--repo", str(leaked), "--title", "Deploy something to mirrors",
                   "--agent", "claude", "--summary", "intent text for the deploy task",
                   "--paths", "a.sh,b.sh", "--skip-awareness"])
    assert rc == 2
    assert "must be a directory" in capsys.readouterr().err
    assert not (leaked / ".agent-state").exists()


def test_task_claim_wrong_agent_exit2_then_force(repo):
    assert _start(repo, agent="codex") == 0
    task_id = _only_task(repo)["id"]
    assert cli.main(["task-claim", "--repo", str(repo), "--task-id", task_id, "--agent", "claude"]) == 2
    assert cli.main(["task-claim", "--repo", str(repo), "--task-id", task_id, "--agent", "claude",
                     "--force"]) == 0
    assert _only_task(repo)["agent"] == "claude"


def test_conflict_check(repo):
    assert _start(repo) == 0
    assert cli.main(["conflict-check", "--repo", str(repo), "--paths", "src/unit_a.py"]) == 2
    assert cli.main(["conflict-check", "--repo", str(repo), "--paths", "src/other_zzz.py"]) == 0


def test_conflict_check_file_as_repo_clean_exit2(repo, tmp_path, capsys):
    """regression-space-separated-paths: a file path leaking into
    --repo (e.g. the 2nd of a space-separated -Paths list in the PS wrapper) must exit cleanly (code 2)
    with a clear 'must be a directory' message -- NOT a traceback -- for conflict-check just as for
    task-start. The PS wrapper now also disables positional binding so the leak cannot happen there."""
    leaked = tmp_path / "test_private_service_builder_retry_reexecutes.py"
    leaked.write_text("def test_x():\n    pass\n", encoding="utf-8")
    rc = cli.main(["conflict-check", "--repo", str(leaked), "--paths", "a.py,b.py"])
    assert rc == 2
    assert "must be a directory" in capsys.readouterr().err


def test_handoff_weak_quality_exit3(repo):
    assert _start(repo) == 0
    task_id = _only_task(repo)["id"]
    assert cli.main(["task-handoff", "--repo", str(repo), "--task-id", task_id, "--agent", "claude",
                     "--summary", "x", "--status", "wip"]) == 3


def test_handoff_wip_then_complete(repo):
    assert _start(repo) == 0
    task_id = _only_task(repo)["id"]
    assert cli.main(["task-handoff", "--repo", str(repo), "--task-id", task_id, "--agent", "claude",
                     "--summary", "handed off mid-work for the unit scenario now",
                     "--evidence", "ran the unit coordination checks; evidence here",
                     "--next", "resume the lane later", "--status", "wip"]) == 0
    assert _only_task(repo)["status"] == "handoff"
    assert cli.main([
        "task-memory", "--repo", str(repo), "--task-id", task_id, "--agent", "claude",
        "--kind", "graph_query", "--query", "coordination cli behavior",
        "--evidence", "memory graph query receipt",
    ]) == 0
    assert cli.main([
        "task-memory", "--repo", str(repo), "--task-id", task_id, "--agent", "claude",
        "--kind", "memory_read", "--store", "shared-memory",
        "--memory-name", "global/factory-doctrine-and-protocols",
        "--evidence", "semantic memory memory read receipt",
    ]) == 0
    # complete handoff: the deterministic work-state gate fixture authorizes completion.
    assert cli.main(["task-handoff", "--repo", str(repo), "--task-id", task_id, "--agent", "claude",
                     "--summary", "completed the lane for the unit scenario now",
                     "--evidence", "ran the unit coordination checks; all green",
                     "--next", "no further action", "--status", "complete"]) == 0
    task = _only_task(repo)
    assert task["status"] == "completed"
    assert task["resolution"] == "completed"


def test_complete_handoff_blocks_until_memory_receipts(repo, capsys):
    assert _start(repo) == 0
    task_id = _only_task(repo)["id"]
    args = [
        "task-handoff", "--repo", str(repo), "--task-id", task_id, "--agent", "claude",
        "--summary", "completed the memory compliance gate scenario",
        "--evidence", "focused tests passed with interpreted evidence",
        "--next", "no further action", "--status", "complete",
    ]
    assert cli.main(args) == 5
    assert "Memory compliance gate failed" in capsys.readouterr().out
    assert _only_task(repo)["status"] == "claimed"


def test_no_relevant_memory_receipt_is_explicit_and_compliant(repo):
    assert _start(repo) == 0
    task_id = _only_task(repo)["id"]
    assert cli.main([
        "task-memory", "--repo", str(repo), "--task-id", task_id, "--agent", "claude",
        "--kind", "graph_query", "--query", "isolated unit scenario",
        "--evidence", "graph query returned no relevant result",
    ]) == 0
    assert cli.main([
        "task-memory", "--repo", str(repo), "--task-id", task_id, "--agent", "claude",
        "--kind", "no_relevant_memory", "--query", "isolated unit scenario",
        "--reason", "No result applied to this isolated fixture.",
        "--evidence", "bounded graph query readback recorded",
    ]) == 0
    assert _only_task(repo)["memory_compliance"]["receipts"]


def test_task_close_removes_locks(repo):
    assert _start(repo) == 0
    task_id = _only_task(repo)["id"]
    assert list((_store(repo) / "locks").glob("*.json"))  # a lock was written
    assert cli.main(["task-close", "--repo", str(repo), "--task-id", task_id, "--agent", "claude"]) == 0
    assert _only_task(repo)["status"] == "closed"
    assert not list((_store(repo) / "locks").glob("*.json"))  # locks released


def test_worktree_create(repo):
    assert _start(repo) == 0
    task_id = _only_task(repo)["id"]
    assert cli.main(["worktree-create", "--repo", str(repo), "--task-id", task_id,
                     "--agent", "claude"]) == 0
    task = _only_task(repo)
    assert task["status"] == "in_progress"
    assert task["branch"] == f"agent/claude/{task_id}"
    assert (_store(repo) / "worktrees" / f"{task_id}.json").exists()
