# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import agent_deploy


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text("[project]\nname='agentready'\n", encoding="utf-8")
    (source / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    return source


class FakeRunner:
    def __init__(self, bin_dir: Path):
        self.bin_dir = bin_dir
        self.commands: list[list[str]] = []

    def __call__(self, command, **_kwargs):
        argv = [str(value) for value in command]
        self.commands.append(argv)
        stdout = str(self.bin_dir) if argv[-3:] == ["tool", "dir", "--bin"] else ""
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")


def test_agent_deployment_is_noninteractive_machine_readable(capsys):
    assert agent_deploy.main(["--mode", "agent", "--yes"]) == 2
    assert "requires both --yes and --json" in capsys.readouterr().err


def test_dry_run_returns_deterministic_plan(tmp_path: Path):
    source = _source(tmp_path)
    payload = agent_deploy.deploy(
        source=source,
        mode="agent",
        target_repo=None,
        runtime_home=None,
        force=True,
        dry_run=True,
        uv_path="uv",
    )
    assert payload["overall"] == "PLANNED"
    steps = payload["steps"]
    assert steps[0]["command"] == ["uv", "tool", "install", "--force", str(source.resolve())]
    assert all(step["status"] == "PLANNED" for step in steps)


def test_deploy_installs_verifies_and_bootstraps_target(tmp_path: Path):
    source = _source(tmp_path)
    target = tmp_path / "repo"
    target.mkdir()
    (target / ".git").mkdir()
    bin_dir = tmp_path / "bin"
    runner = FakeRunner(bin_dir)
    payload = agent_deploy.deploy(
        source=source,
        mode="agent",
        target_repo=target,
        runtime_home=tmp_path / "runtime",
        force=True,
        dry_run=False,
        runner=runner,
        uv_path="uv",
    )
    assert payload["overall"] == "PASS"
    names = [step["name"] for step in payload["steps"]]
    assert names == [
        "install",
        "resolve-tool-bin",
        "verify-agentready",
        "verify-agent-deploy",
        "verify-agent-bootstrap-repo",
        "verify-agent-coordination",
        "verify-factory-capture",
        "bootstrap-repository",
    ]
    assert runner.commands[-1][-2:] == ["--repo", str(target.resolve())]
    assert json.loads(json.dumps(payload))["schema"] == "agentready.deployment.v1"


def test_deploy_refuses_missing_target_directory(tmp_path: Path):
    source = _source(tmp_path)
    runner = FakeRunner(tmp_path / "bin")
    with pytest.raises(ValueError, match="does not exist"):
        agent_deploy.deploy(
            source=source,
            mode="human",
            target_repo=tmp_path / "missing",
            runtime_home=None,
            force=False,
            dry_run=False,
            runner=runner,
            uv_path="uv",
        )
    assert runner.commands == []


def test_dry_run_refuses_non_git_target_before_install(tmp_path: Path):
    source = _source(tmp_path)
    target = tmp_path / "not-a-repo"
    target.mkdir()
    runner = FakeRunner(tmp_path / "bin")
    with pytest.raises(ValueError, match="not a Git working-tree root"):
        agent_deploy.deploy(
            source=source,
            mode="agent",
            target_repo=target,
            runtime_home=None,
            force=False,
            dry_run=True,
            runner=runner,
            uv_path="uv",
        )
    assert runner.commands == []


def test_source_identity_must_be_agentready(tmp_path: Path):
    source = _source(tmp_path)
    (source / "pyproject.toml").write_text("[project]\nname='different-project'\n", encoding="utf-8")
    with pytest.raises(ValueError, match="project.name"):
        agent_deploy.deploy(
            source=source,
            mode="human",
            target_repo=None,
            runtime_home=None,
            force=False,
            dry_run=True,
            uv_path="uv",
        )


def test_runner_timeout_becomes_failed_step(tmp_path: Path):
    source = _source(tmp_path)

    def timed_out(command, **_kwargs):
        raise subprocess.TimeoutExpired(command, 300)

    payload = agent_deploy.deploy(
        source=source,
        mode="agent",
        target_repo=None,
        runtime_home=None,
        force=False,
        dry_run=False,
        runner=timed_out,
        uv_path="uv",
    )
    assert payload["overall"] == "FAIL"
    assert payload["steps"][0]["name"] == "install"
    assert payload["steps"][0]["status"] == "FAIL"


def test_json_cli_contract_for_agent_dry_run(tmp_path: Path, capsys, monkeypatch):
    source = _source(tmp_path)
    monkeypatch.setattr(agent_deploy.shutil, "which", lambda _name: "uv")
    result = agent_deploy.main([
        "--mode",
        "agent",
        "--yes",
        "--json",
        "--dry-run",
        "--source",
        str(source),
    ])
    assert result == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["overall"] == "PLANNED"
    assert payload["mode"] == "agent"
