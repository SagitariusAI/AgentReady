from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from factory_capture.events import all_events
from factory_capture.runner import run_command
from factory_capture.store import Store


def _store(tmp_path) -> Store:
    store = Store(tmp_path / ".factory_capture")
    store.init()
    return store


def _git_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    for args in (["init"], ["config", "user.email", "t@t.test"], ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=str(path), capture_output=True, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "init"], cwd=str(path),
                   capture_output=True, check=True)
    return path


def test_run_captures_successful_command(tmp_path, capsys):
    store = _store(tmp_path)
    ev = run_command(store, [sys.executable, "-c", "print('OK-OUT')"], cwd=tmp_path)
    assert "OK-OUT" in capsys.readouterr().out  # streamed live to the terminal
    assert ev["exit_code"] == 0 and ev["status"] == "success"
    assert ev["event_type"] == "command_run" and ev["duration_ms"] >= 0
    assert ev["git_before"] is not None and ev["git_after"] is not None
    assert all_events(store)[-1]["event_id"] == ev["event_id"]


def test_run_captures_failing_command_and_preserves_exit_code(tmp_path):
    store = _store(tmp_path)
    ev = run_command(store, [sys.executable, "-c", "import sys; sys.exit(7)"], cwd=tmp_path)
    assert ev["exit_code"] == 7 and ev["status"] == "failure"


def test_run_command_not_found_is_captured_not_crash(tmp_path):
    store = _store(tmp_path)
    ev = run_command(store, ["this-command-does-not-exist-xyz"], cwd=tmp_path)
    assert ev["exit_code"] == 127 and ev["status"] == "error"


def test_run_writes_stdout_and_stderr_logs(tmp_path):
    store = _store(tmp_path)
    ev = run_command(store, [sys.executable, "-c",
                             "import sys; print('to-out'); sys.stderr.write('to-err\\n')"], cwd=tmp_path)
    out_log = store.root / ev["stdout_log"]
    err_log = store.root / ev["stderr_log"]
    assert "to-out" in out_log.read_text(encoding="utf-8")
    assert "to-err" in err_log.read_text(encoding="utf-8")
    assert ev["stdout_sha256"] and ev["stderr_sha256"]


def test_run_redacts_secrets_in_logs_and_event(tmp_path):
    store = _store(tmp_path)
    token = "ghp_" + "cd" * 18
    ev = run_command(store, [sys.executable, "-c", f"print('leak {token}')"], cwd=tmp_path)
    out_log = (store.root / ev["stdout_log"]).read_text(encoding="utf-8")
    assert token not in out_log and "[REDACTED:github_token]" in out_log
    assert ev["redaction"]["applied"] is True
    assert any(f["kind"] == "github_token" for f in ev["redaction"]["findings"])
    # the raw secret must not appear anywhere in the persisted JSONL
    assert token not in (store.events_path).read_text(encoding="utf-8")


def test_run_captures_git_changes(tmp_path):
    repo = _git_repo(tmp_path / "r")
    store = Store(repo / ".factory_capture")
    store.init()
    ev = run_command(store, [sys.executable, "-c",
                             "from pathlib import Path; Path('made.txt').write_text('x')"], cwd=repo)
    assert ev["git_after"]["is_git_repo"] is True
    assert "made.txt" in ev["git_after"]["untracked_files"]
    assert ev["repo_root"] == str(Path(repo))
