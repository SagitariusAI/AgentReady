# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import agent_session_reentry as reentry


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    (path / "tracked.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "base"],
        cwd=path,
        check=True,
        capture_output=True,
    )
    return path


def _task(repo: Path) -> dict:
    return {"id": "t1", "agent": "claude", "status": "in_progress", "repo_root": str(repo), "paths": ["src"]}


def _green(monkeypatch, repo: Path) -> None:
    monkeypatch.setattr(reentry, "unread_urgent_messages", lambda _agent: [])
    monkeypatch.setattr(reentry, "find_active_task", lambda _a, _t, _r: (_task(repo), "ok"))
    monkeypatch.setattr(reentry, "source_control_status", lambda _r: {"status": "PASS", "mode": "local-only"})
    monkeypatch.setattr(reentry, "harness_snapshot", lambda _a, _r: {"fingerprint": "fp"})


def test_urgent_messages_aggregate_but_temp_fixture_can_be_explicitly_scanned(tmp_path: Path) -> None:
    message = tmp_path / "demo" / "messages" / "stop.json"
    message.parent.mkdir(parents=True)
    message.write_text(json.dumps({
        "id": "stop", "to": "claude", "from": "reviewer", "read": False,
        "precedence": "PRIORITY", "type": "WARNORD", "subject": "hold",
    }), encoding="utf-8")
    assert reentry.unread_urgent_messages("claude", tmp_path) == [{
        "id": "stop", "from": "reviewer", "precedence": "PRIORITY", "type": "WARNORD", "store": "demo",
    }]


def test_task_scan_ignores_non_object_entries(tmp_path: Path) -> None:
    task_dir = tmp_path / "demo" / "tasks"
    task_dir.mkdir(parents=True)
    (task_dir / "null.json").write_text("null", encoding="utf-8")
    (task_dir / "valid.json").write_text(json.dumps({"id": "valid"}), encoding="utf-8")
    assert reentry.all_tasks(tmp_path) == [{"id": "valid", "_store": "demo"}]


def test_dirty_paths_preserve_porcelain_leading_space(repo: Path) -> None:
    (repo / "tracked.txt").write_text("changed\n", encoding="utf-8")
    assert reentry.dirty_paths(repo) == ["tracked.txt"]


def test_issue_blocks_on_warning_and_source_divergence(monkeypatch, repo: Path) -> None:
    monkeypatch.setattr(reentry, "unread_urgent_messages", lambda _agent: [{"id": "stop"}])
    monkeypatch.setattr(reentry, "find_active_task", lambda _a, _t, _r: (_task(repo), "ok"))
    monkeypatch.setattr(reentry, "source_control_status", lambda _r: {"status": "FAIL"})
    monkeypatch.setattr(reentry, "harness_snapshot", lambda _a, _r: {"fingerprint": "fp"})
    result = reentry.evaluate_issue(
        agent="claude", repo=repo, session_id="s1", task_id="t1",
        acknowledgements={name: True for name in reentry.REQUIRED_ACKS},
    )
    assert result["status"] == "BLOCKED"
    assert "unread_urgent:stop" in result["failures"]
    assert "source_control_not_authoritative" in result["failures"]


def test_issue_and_verify_detect_harness_change(monkeypatch, tmp_path: Path, repo: Path) -> None:
    monkeypatch.setenv("AGENTREADY_SESSION_REENTRY_DIR", str(tmp_path / "receipts"))
    _green(monkeypatch, repo)
    result = reentry.issue_receipt(
        agent="claude", repo=repo, session_id="session", task_id="t1",
        acknowledgements={name: True for name in reentry.REQUIRED_ACKS},
    )
    assert result["status"] == "PASS"
    assert reentry.verify_receipt(agent="claude", repo=repo, session_id="session")["status"] == "PASS"
    monkeypatch.setattr(reentry, "harness_snapshot", lambda _a, _r: {"fingerprint": "changed"})
    assert "harness_changed_since_receipt" in reentry.verify_receipt(
        agent="claude", repo=repo, session_id="session"
    )["failures"]


def test_acked_dirty_in_repo_harness_edit_is_forgiven_but_unacked_still_blocks(
    monkeypatch, tmp_path: Path, repo: Path
) -> None:
    monkeypatch.setenv("AGENTREADY_SESSION_REENTRY_DIR", str(tmp_path / "receipts"))
    _green(monkeypatch, repo)
    hfile = str((repo / "src" / "harness_bit.py").resolve())
    # Issue with a snapshot that enumerates its files; the in-repo harness file is
    # acknowledged dirty (it falls under the task's claimed "src" lane).
    monkeypatch.setattr(reentry, "harness_snapshot",
                        lambda _a, _r: {"fingerprint": "fp", "files": {hfile: "v1"}})
    monkeypatch.setattr(reentry, "dirty_paths", lambda _r: ["src/harness_bit.py"])
    issued = reentry.issue_receipt(
        agent="claude", repo=repo, session_id="session", task_id="t1",
        acknowledgements={name: True for name in reentry.REQUIRED_ACKS},
        acknowledge_dirty=True,
    )
    assert issued["status"] == "PASS"
    # The acknowledged in-repo harness file changes: the fingerprint differs, but the
    # edit was claimed, so verify FORGIVES it instead of wedging the session.
    monkeypatch.setattr(reentry, "harness_snapshot",
                        lambda _a, _r: {"fingerprint": "changed", "files": {hfile: "v2"}})
    assert reentry.verify_receipt(agent="claude", repo=repo, session_id="session")["status"] == "PASS"
    # A DIFFERENT, unacknowledged harness file changing still forces re-entry.
    other = str((repo / "src" / "other_bit.py").resolve())
    monkeypatch.setattr(reentry, "harness_snapshot",
                        lambda _a, _r: {"fingerprint": "changed2", "files": {hfile: "v2", other: "z"}})
    assert "harness_changed_since_receipt" in reentry.verify_receipt(
        agent="claude", repo=repo, session_id="session"
    )["failures"]


def test_dirty_state_requires_claim_coverage_and_ack(monkeypatch, repo: Path) -> None:
    _green(monkeypatch, repo)
    (repo / "src").mkdir()
    (repo / "src" / "change.py").write_text("x=1\n", encoding="utf-8")
    common = dict(
        agent="claude", repo=repo, session_id="s1", task_id="t1",
        acknowledgements={name: True for name in reentry.REQUIRED_ACKS},
    )
    assert "dirty_state_requires_ack" in reentry.evaluate_issue(**common)["failures"]
    assert reentry.evaluate_issue(**common, acknowledge_dirty=True)["status"] == "PASS"


def test_local_only_and_configured_remote_authority(monkeypatch, repo: Path) -> None:
    monkeypatch.delenv("AGENTREADY_AUTHORITY_REMOTE", raising=False)
    assert reentry.source_control_status(repo)["mode"] == "local-only"
    monkeypatch.setenv("AGENTREADY_AUTHORITY_REMOTE", "missing-remote")
    assert reentry.source_control_status(repo)["status"] == "FAIL"


def test_bootstrap_is_narrow() -> None:
    assert reentry.is_bootstrap_command("git status && agent-coordination task-status --repo .")
    assert not reentry.is_bootstrap_command("python train.py")
    assert not reentry.is_bootstrap_command("git push github main")


def test_pre_tool_hook_denies_mutation_without_receipt(monkeypatch, repo: Path) -> None:
    monkeypatch.setattr(reentry, "verify_receipt", lambda **_kwargs: {
        "status": "BLOCKED", "failures": ["receipt_unavailable"]
    })
    payload = {"session_id": "s", "cwd": str(repo), "tool_name": "Write", "tool_input": {
        "file_path": str(repo / "new.txt")
    }}
    result = reentry.hook_response("pre-tool-use", payload, "claude")
    assert result["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_receipt_contains_hashes_not_message_or_source_content(monkeypatch, repo: Path) -> None:
    _green(monkeypatch, repo)
    result = reentry.evaluate_issue(
        agent="claude", repo=repo, session_id="opaque-session", task_id="t1",
        acknowledgements={name: True for name in reentry.REQUIRED_ACKS},
    )
    encoded = json.dumps(result)
    assert "base\\n" not in encoded
    assert "body" not in encoded
