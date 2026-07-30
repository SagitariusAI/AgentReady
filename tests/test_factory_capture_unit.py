# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
import sys

import pytest

from factory_capture import common, events, gitstate, redaction
from factory_capture.store import Store, resolve_store


def _init_git_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    for args in (["init"], ["config", "user.email", "t@t.test"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=str(path),
                   capture_output=True, check=True)
    return path


# --------------------------------------------------------------------------- common
def test_now_iso_is_utc():
    assert common.now_iso().endswith("+00:00")


def test_gen_event_id_unique_and_sortable():
    ids = [common.gen_event_id() for _ in range(200)]
    assert len(set(ids)) == 200  # collision-resistant
    prefixes = [i.split("-")[0] for i in ids]
    assert prefixes == sorted(prefixes)  # time-monotonic prefix => sortable


def test_jsonl_roundtrip(tmp_path):
    p = tmp_path / "e.jsonl"
    common.append_jsonl(p, {"a": 1})
    common.append_jsonl(p, {"b": 2})
    assert common.read_jsonl(p) == [{"a": 1}, {"b": 2}]


def test_sha256_text_deterministic():
    assert common.sha256_text("x") == common.sha256_text("x")
    assert common.sha256_text("x") != common.sha256_text("y")


# --------------------------------------------------------------------------- redaction
def test_redaction_removes_obvious_secrets():
    secret = "ghp_" + "ab" * 18
    text = (f"email me@example.com token {secret} key AKIA1234567890ABCDEF "
            f"openai sk-{'a' * 30} API_KEY=supersecretvalue bearer {'z' * 30}")
    red, findings = redaction.redact_text(text)
    assert secret not in red and "me@example.com" not in red and "supersecretvalue" not in red
    assert "AKIA1234567890ABCDEF" not in red
    kinds = {f["kind"] for f in findings}
    assert {"github_token", "email", "aws_access_key", "openai_key", "env_secret"} <= kinds
    assert all(f["count"] >= 1 for f in findings)


def test_redaction_empty_and_clean():
    assert redaction.redact_text("") == ("", [])
    red, findings = redaction.redact_text("just normal output, nothing secret")
    assert findings == [] and red == "just normal output, nothing secret"


def test_redaction_jwt_and_private_key():
    jwt = "eyJhbGciOi.eyJzdWIiOi.SflKxwRJSM"
    pk = "-----BEGIN RSA " + "PRIVATE KEY-----\nabc\n-----END RSA " + "PRIVATE KEY-----"
    red, findings = redaction.redact_text(f"t {jwt} {pk}")
    assert "eyJhbGciOi" not in red and "abc" not in red
    assert {f["kind"] for f in findings} == {"jwt", "private_key"}


# --------------------------------------------------------------------------- gitstate
def test_capture_git_state_non_git(tmp_path):
    state = gitstate.capture_git_state(tmp_path)
    assert state["is_git_repo"] is False
    assert state["branch"] == "" and state["commit"] == "" and state["changed_files"] == []


def test_capture_git_state_in_repo(tmp_path):
    repo = _init_git_repo(tmp_path / "r")
    (repo / "new.txt").write_text("hi", encoding="utf-8")
    state = gitstate.capture_git_state(repo)
    assert state["is_git_repo"] is True
    assert state["commit"] and state["dirty"] is True
    assert "new.txt" in state["untracked_files"]


def test_remote_is_sanitized(tmp_path):
    repo = _init_git_repo(tmp_path / "r")
    remote = "https://" + "user:" + "secretpw@" + "github.com/x/y.git"
    subprocess.run(["git", "remote", "add", "origin", remote],
                   cwd=str(repo), capture_output=True, check=True)
    state = gitstate.capture_git_state(repo)
    assert "secretpw" not in state["remote_sanitized"]
    assert state["remote_sanitized"] == "https://github.com/x/y.git"
    assert state["remote_sha256"]


# --------------------------------------------------------------------------- store
def test_store_init_creates_layout(tmp_path):
    store = Store(tmp_path / ".factory_capture")
    result = store.init()
    assert result["created"] is True and store.exists()
    for d in (store.logs_dir, store.artifacts_dir, store.sessions_dir, store.hooks_dir):
        assert d.is_dir()
    assert store.index_path.exists() and common.read_json(store.config_path)["schema"] == "sf.capture_store.v0.1"


def test_store_init_refuses_clobber_without_force(tmp_path):
    store = Store(tmp_path / ".factory_capture")
    store.init()
    again = store.init()
    assert again["created"] is False and again["already_existed"] is True
    assert store.init(force=True)["created"] is True


def test_resolve_store_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("FACTORY_CAPTURE_DIR", str(tmp_path / "custom"))
    assert resolve_store().root == tmp_path / "custom"


# --------------------------------------------------------------------------- events
def test_new_event_schema_complete_and_validates_type():
    ev = events.new_event("command_run")
    for key in ("schema", "event_id", "event_type", "timestamp_start", "redaction", "status"):
        assert key in ev
    assert ev["schema"] == "sf.capture_event.v0.1"
    with pytest.raises(ValueError):
        events.new_event("not_a_type")


def test_append_event_writes_jsonl_and_sqlite_index(tmp_path):
    store = Store(tmp_path / ".factory_capture")
    store.init()
    ev = events.new_event("command_run", command=[sys.executable, "-c", "pass"], exit_code=0)
    events.append_event(store, ev)
    assert events.count_events(store) == 1
    assert events.all_events(store)[0]["event_id"] == ev["event_id"]
    con = store.connect()
    row = con.execute("select event_id, event_type, exit_code from events").fetchone()
    con.close()
    assert row == (ev["event_id"], "command_run", 0)


def test_append_event_replay_is_idempotent_and_conflicts_fail(tmp_path):
    store = Store(tmp_path / ".factory_capture")
    store.init(repo_root=tmp_path)
    ev = events.new_event("command_run", command=["python", "-V"], exit_code=0)
    events.append_event(store, ev)
    events.append_event(store, dict(ev))
    assert len(list(events.iter_events(store))) == 1
    with pytest.raises(ValueError, match="replay conflict"):
        events.append_event(store, {**ev, "exit_code": 1})
