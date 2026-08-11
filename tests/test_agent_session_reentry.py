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
    monkeypatch.setattr(reentry, "unread_urgent_messages", lambda _agent, **_kw: [])
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
    monkeypatch.setattr(reentry, "unread_urgent_messages", lambda _agent, **_kw: [{"id": "stop"}])
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


def _urgent_message(tmp_path: Path, **fields) -> Path:
    message = tmp_path / "demo" / "messages" / f"{fields.get('id', 'm')}.json"
    message.parent.mkdir(parents=True, exist_ok=True)
    body = {"to": "claude", "read": False, "precedence": "IMMEDIATE", "type": "MSG"}
    body.update(fields)
    message.write_text(json.dumps(body), encoding="utf-8")
    return message


def test_urgent_to_specific_session_blocks_only_that_session(tmp_path: Path) -> None:
    _urgent_message(tmp_path, id="directed", to_session="alpha", subject="hold")
    # The addressed session sees (and is blocked by) the flag.
    mine = reentry.unread_urgent_messages("claude", tmp_path, session_id="alpha")
    assert [row["id"] for row in mine] == ["directed"]
    # A sibling session of the same agent name is NOT blocked by it.
    peer = reentry.unread_urgent_messages("claude", tmp_path, session_id="beta")
    assert peer == []
    # An empty reader session_id stays name-wide (no regression): still sees it.
    namewide = reentry.unread_urgent_messages("claude", tmp_path, session_id="")
    assert [row["id"] for row in namewide] == ["directed"]


def test_urgent_without_to_session_stays_name_wide(tmp_path: Path) -> None:
    _urgent_message(tmp_path, id="broadcast")
    for session in ("alpha", "beta", ""):
        rows = reentry.unread_urgent_messages("claude", tmp_path, session_id=session)
        assert [row["id"] for row in rows] == ["broadcast"]


def test_session_does_not_fence_its_own_broadcast(tmp_path: Path) -> None:
    # A message the reader itself sent (from_session == its own session) must not
    # block its own receipt; a message from a different session still does.
    _urgent_message(tmp_path, id="self", from_session="alpha")
    assert reentry.unread_urgent_messages("claude", tmp_path, session_id="alpha") == []
    _urgent_message(tmp_path, id="other", from_session="beta")
    ids = {row["id"] for row in reentry.unread_urgent_messages("claude", tmp_path, session_id="alpha")}
    assert ids == {"other"}


def test_receipt_path_is_repo_scoped_no_cross_repo_overwrite(tmp_path: Path) -> None:
    monkey_root = tmp_path / "receipts"
    import os
    os.environ["AGENTREADY_SESSION_REENTRY_DIR"] = str(monkey_root)
    try:
        one = reentry.receipt_path("claude", "session", tmp_path / "repo-one")
        two = reentry.receipt_path("claude", "session", tmp_path / "repo-two")
        # Same agent + same session but different repos must not collide.
        assert one != two
        assert one.name != two.name
        # No repo argument keeps the legacy (un-scoped) name for backward safety.
        legacy = reentry.receipt_path("claude", "session")
        assert legacy.name == "claude-" + __import__("hashlib").sha256(
            b"session").hexdigest()[:16] + ".json"
        assert legacy.name != one.name
    finally:
        del os.environ["AGENTREADY_SESSION_REENTRY_DIR"]


def test_issue_then_verify_survives_a_second_repo_issue(monkeypatch, tmp_path: Path) -> None:
    # Issuing a receipt for a SECOND repo in the same session must not clobber the
    # first repo's receipt (the cross-repo overwrite lockout that Fix C closes).
    monkeypatch.setenv("AGENTREADY_SESSION_REENTRY_DIR", str(tmp_path / "receipts"))
    repo_one = _init_repo(tmp_path / "one")
    repo_two = _init_repo(tmp_path / "two")

    def _green_for(target: Path) -> None:
        monkeypatch.setattr(reentry, "unread_urgent_messages", lambda _a, **_kw: [])
        monkeypatch.setattr(reentry, "find_active_task",
                            lambda _a, _t, _r: ({"id": "t1", "agent": "claude", "status": "in_progress",
                                                 "repo_root": str(target), "paths": ["src"]}, "ok"))
        monkeypatch.setattr(reentry, "source_control_status",
                            lambda _r: {"status": "PASS", "mode": "local-only"})
        monkeypatch.setattr(reentry, "harness_snapshot", lambda _a, _r: {"fingerprint": "fp"})

    _green_for(repo_one)
    assert reentry.issue_receipt(
        agent="claude", repo=repo_one, session_id="s", task_id="t1",
        acknowledgements={name: True for name in reentry.REQUIRED_ACKS},
    )["status"] == "PASS"
    _green_for(repo_two)
    assert reentry.issue_receipt(
        agent="claude", repo=repo_two, session_id="s", task_id="t1",
        acknowledgements={name: True for name in reentry.REQUIRED_ACKS},
    )["status"] == "PASS"
    # The first repo's receipt is still intact and verifies.
    _green_for(repo_one)
    assert reentry.verify_receipt(agent="claude", repo=repo_one, session_id="s")["status"] == "PASS"


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=path, check=True, capture_output=True)
    (path / "tracked.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "base"],
        cwd=path, check=True, capture_output=True,
    )
    return path


def test_read_json_retries_then_succeeds_on_transient_decode_error(tmp_path: Path) -> None:
    target = tmp_path / "flaky.json"
    target.write_text("{\"ok\": true}", encoding="utf-8")
    calls = {"n": 0}
    real_read_text = Path.read_text

    def flaky_read_text(self, *args, **kwargs):
        if self == target and calls["n"] < 2:
            calls["n"] += 1
            return ""  # empty content -> JSONDecodeError, simulating a mid-write read
        return real_read_text(self, *args, **kwargs)

    original_sleep = reentry.time.sleep
    reentry.time.sleep = lambda _s: None
    Path.read_text = flaky_read_text
    try:
        assert reentry._read_json(target) == {"ok": True}
        assert calls["n"] == 2
    finally:
        Path.read_text = real_read_text
        reentry.time.sleep = original_sleep


def test_read_json_missing_file_raises_immediately(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        reentry._read_json(tmp_path / "does-not-exist.json")


def test_read_json_raises_after_exhausting_attempts(tmp_path: Path) -> None:
    target = tmp_path / "corrupt.json"
    target.write_text("not json at all", encoding="utf-8")
    original_sleep = reentry.time.sleep
    reentry.time.sleep = lambda _s: None
    try:
        with pytest.raises(json.JSONDecodeError):
            reentry._read_json(target, attempts=3)
    finally:
        reentry.time.sleep = original_sleep
