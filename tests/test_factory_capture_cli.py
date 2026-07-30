# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import subprocess
import sys

import factory_capture
from factory_capture.cli import main


def _git_repo_cwd(tmp_path, monkeypatch):
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.test"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(tmp_path), capture_output=True, check=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_init_creates_store_and_refuses_clobber(tmp_path, monkeypatch, capsys):
    _git_repo_cwd(tmp_path, monkeypatch)
    assert main(["init"]) == 0
    assert (tmp_path / ".factory_capture" / "config.json").exists()
    assert "initialized" in capsys.readouterr().out
    assert main(["init"]) == 1  # no clobber
    assert main(["init", "--force"]) == 0


def test_commands_require_init(tmp_path, monkeypatch, capsys):
    _git_repo_cwd(tmp_path, monkeypatch)
    assert main(["status"]) == 1
    assert "init" in capsys.readouterr().err


def test_run_via_cli_success_and_failure(tmp_path, monkeypatch):
    _git_repo_cwd(tmp_path, monkeypatch)
    main(["init"])
    assert main(["run", "--", sys.executable, "-c", "print('hi')"]) == 0
    assert main(["run", "--", sys.executable, "-c", "import sys; sys.exit(5)"]) == 5


def test_run_without_command_is_usage_error(tmp_path, monkeypatch):
    _git_repo_cwd(tmp_path, monkeypatch)
    main(["init"])
    assert main(["run"]) == 2
    assert main(["run", "--"]) == 2


def test_status_tail_note_summarize(tmp_path, monkeypatch, capsys):
    _git_repo_cwd(tmp_path, monkeypatch)
    main(["init"])
    main(["run", "--", sys.executable, "-c", "print('x')"])
    capsys.readouterr()

    assert main(["status"]) == 0
    assert "Factory Capture Status" in capsys.readouterr().out

    assert main(["note", "hello note"]) == 0
    capsys.readouterr()

    assert main(["tail", "-n", "5"]) == 0
    assert "command_run" in capsys.readouterr().out

    assert main(["tail", "--json"]) == 0
    json_out = capsys.readouterr().out.strip().splitlines()
    assert all(json.loads(line)["schema"] == "sf.capture_event.v0.1" for line in json_out)

    assert main(["summarize"]) == 0
    summary_out = capsys.readouterr().out
    assert "Factory Capture Summary" in summary_out and "Commands: 1" in summary_out


def test_summarize_runs_without_ollama(tmp_path, monkeypatch, capsys):
    _git_repo_cwd(tmp_path, monkeypatch)
    main(["init"])
    capsys.readouterr()
    assert main(["summarize", "--ollama"]) == 0  # degrades gracefully when ollama absent
    assert "Factory Capture Summary" in capsys.readouterr().out


def test_hooks_install_status_uninstall_via_cli(tmp_path, monkeypatch, capsys):
    _git_repo_cwd(tmp_path, monkeypatch)
    main(["init"])
    capsys.readouterr()
    assert main(["hooks", "install"]) == 0
    assert "installed" in capsys.readouterr().out
    assert main(["hooks", "status"]) == 0
    assert json.loads(capsys.readouterr().out)["post-commit"] is True
    assert main(["hooks", "uninstall"]) == 0


def test_public_api_surface_is_stable():
    expected = {
        "Store", "resolve_store", "run_command", "new_event", "append_event",
        "capture_git_state", "redact_text", "install_hooks", "uninstall_hooks",
        "summarize", "main",
    }
    assert expected <= set(factory_capture.__all__)
    for name in expected:
        assert hasattr(factory_capture, name)
    assert factory_capture.CAPTURE_EVENT_SCHEMA == "sf.capture_event.v0.1"
