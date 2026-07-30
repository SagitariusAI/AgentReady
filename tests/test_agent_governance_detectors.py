# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Public support for test agent governance detectors."""
from __future__ import annotations

import json
import math
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import agent_governance_detectors as gd
import agent_runtime_paths
from agent_coordination.store import ensure_state, state_dir


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_runtime_paths, "COORDINATION_ROOT", tmp_path / "coordination")
    monkeypatch.setattr(agent_runtime_paths, "WORKTREE_ROOT", tmp_path / "worktrees")
    work = tmp_path / "repo"
    work.mkdir()
    subprocess.run(["git", "init"], cwd=str(work), capture_output=True, check=True)
    subprocess.run(["git", "commit", "--allow-empty", "-m", "init"], cwd=str(work),
                   capture_output=True, check=False)
    ensure_state(work)
    return work


def _add_task(repo: Path, task_id: str, *, status: str, agent: str, age_hours: float, paths=None) -> None:
    ts = (datetime.now() - timedelta(hours=age_hours)).strftime("%Y-%m-%dT%H:%M:%S")
    rec = {"id": task_id, "status": status, "agent": agent, "updated_at": ts, "paths": paths or []}
    (state_dir(repo, "tasks") / f"{task_id}.json").write_text(json.dumps(rec), encoding="utf-8")


def test_age_hours():
    assert gd._age_hours("") == math.inf
    assert gd._age_hours("not-a-date") == math.inf
    assert 0 <= gd._age_hours(datetime.now().strftime("%Y-%m-%dT%H:%M:%S")) < 1


def test_claim_detectors(repo):
    _add_task(repo, "t1", status="claimed", agent="claude", age_hours=30)       # > 24 -> stale
    _add_task(repo, "t2", status="in_progress", agent="codex", age_hours=10)    # > 6  -> missing handoff
    _add_task(repo, "t3", status="claimed", agent="claude", age_hours=2)        # fresh -> nothing
    _add_task(repo, "t4", status="handoff", agent="claude", age_hours=50)       # not claimed/in_progress
    findings = gd.claim_detector_findings(str(repo))
    kinds = [(f["kind"], f["severity"]) for f in findings]
    assert kinds == [("stale_claim", "warn"), ("missing_handoff", "warn")]
    assert "t1" in findings[0]["message"] and "claimed and forgotten" in findings[0]["message"]
    assert "t2" in findings[1]["message"] and "no handoff" in findings[1]["message"]


def test_no_upstream_short_circuits(repo):
    # a fresh repo has no @{upstream}: unpushed + silent must return [] (no false positives)
    assert gd.unpushed_findings(str(repo)) == []
    assert gd.silent_commit_findings(str(repo)) == []


def test_orphan_single_worktree(repo):
    assert gd.orphan_worktree_findings(str(repo)) == []  # only the main tree -> nothing


def test_orphan_detector_does_not_report_primary_when_run_from_linked_worktree(repo, tmp_path):
    linked = tmp_path / "linked"
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(linked), "HEAD"],
        cwd=str(repo),
        capture_output=True,
        check=True,
    )
    ensure_state(linked)

    findings = gd.orphan_worktree_findings(str(linked))

    assert not any(str(repo) in finding["message"] for finding in findings)


def test_unpushed_and_silent_with_upstream(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_runtime_paths, "COORDINATION_ROOT", tmp_path / "coordination")
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", str(remote)], capture_output=True, check=True)
    work = tmp_path / "repo"
    subprocess.run(["git", "clone", str(remote), str(work)], capture_output=True, check=True)
    cfg = ["-c", "user.email=tester@example.invalid", "-c", "user.name=t"]
    (work / "a.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", *cfg, "add", "-A"], cwd=str(work), capture_output=True, check=False)
    subprocess.run(["git", *cfg, "commit", "-m", "base"], cwd=str(work), capture_output=True, check=False)
    subprocess.run(["git", "push", "-u", "origin", "HEAD"], cwd=str(work), capture_output=True, check=False)
    # an UNPUSHED commit touching uncovered paths -> unpushed_batch + silent_commit
    (work / "b.py").write_text("y = 2\n", encoding="utf-8")
    subprocess.run(["git", *cfg, "add", "-A"], cwd=str(work), capture_output=True, check=False)
    subprocess.run(["git", *cfg, "commit", "-m", "local"], cwd=str(work), capture_output=True, check=False)
    ensure_state(work)

    up = gd.unpushed_findings(str(work))
    assert len(up) == 1 and up[0]["kind"] == "unpushed_batch" and "1 commit(s) ahead" in up[0]["message"]
    silent = gd.silent_commit_findings(str(work))
    assert len(silent) == 1 and silent[0]["kind"] == "silent_commit"

    # now cover b.py with an active claim -> the commit is no longer "silent"
    _add_task(work, "claim1", status="in_progress", agent="claude", age_hours=1, paths=["b.py"])
    assert gd.silent_commit_findings(str(work)) == []


def test_main_clean_vs_problems(repo, capsys):
    assert gd.main(["--repo", str(repo), "--quiet"]) == 0  # clean repo, quiet -> exit 0
    _add_task(repo, "t1", status="claimed", agent="claude", age_hours=30)
    assert gd.main(["--repo", str(repo)]) == 1  # a stale claim -> exit 1
    assert "[governance]" in capsys.readouterr().out
