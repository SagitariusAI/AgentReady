# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Public support for test agent ci local."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import agent_ci_local as ci


@pytest.fixture(autouse=True)
def _deterministic_python(monkeypatch):
    # Make the python-step detection independent of the real .venv location.
    monkeypatch.setattr(ci, "_venv_python", lambda: Path(sys.executable))


def test_decide_pass():
    assert ci.decide([], 2) == {"report_status": "ok", "gate_status": "pass", "exit_code": 0}


def test_decide_fail():
    assert ci.decide(["pytest tests exited 1"], 2) == {
        "report_status": "fail", "gate_status": "fail", "exit_code": 1}


def test_decide_no_steps_is_gate_fail_but_exit_zero():
    # critical semantic: "no steps ran" -> gate fail, report warn, but exit 0
    assert ci.decide([], 0) == {"report_status": "warn", "gate_status": "fail", "exit_code": 0}


def _names(steps):
    return [s["name"] for s in steps]


def test_detect_none(tmp_path):
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    assert ci.detect_steps(tmp_path) == []


def test_detect_python_steps(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    assert _names(ci.detect_steps(tmp_path)) == ["python compile src", "pytest tests"]


def test_detect_pnpm_vs_npm(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    assert _names(ci.detect_steps(tmp_path)) == ["npm test"]
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    assert _names(ci.detect_steps(tmp_path)) == ["pnpm test"]


def test_detect_tox_from_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.tox]\nenvlist = py\n", encoding="utf-8")
    assert "tox" in _names(ci.detect_steps(tmp_path))


def test_detect_order_multiple(tmp_path):
    (tmp_path / "lefthook.yml").write_text("", encoding="utf-8")
    (tmp_path / ".pre-commit-config.yaml").write_text("", encoding="utf-8")
    (tmp_path / "Cargo.toml").write_text("", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    assert _names(ci.detect_steps(tmp_path)) == [
        "lefthook run pre-commit", "pre-commit run --all-files", "cargo test",
        "python compile src", "pytest tests"]


def test_detect_repo_local_ci_replaces_generic_steps(tmp_path):
    (tmp_path / ".agentready").mkdir()
    (tmp_path / ".pre-commit-config.yaml").write_text("", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".agentready" / "ci.json").write_text(
        json.dumps({
            "version": 1,
            "mode": "replace",
            "steps": [
                {
                    "name": "ExampleProject operational gate",
                    "argv": [
                        "pwsh",
                        "-NoProfile",
                        "-File",
                        "scripts/ci/msi-operational-gate.ps1",
                    ],
                    "env": {"JARVIS_CI_PROFILE": "msi-operational"},
                }
            ],
        }),
        encoding="utf-8",
    )

    steps = ci.detect_steps(tmp_path)

    assert steps == [
        {
            "name": "ExampleProject operational gate",
            "argv": [
                "pwsh",
                "-NoProfile",
                "-File",
                "scripts/ci/msi-operational-gate.ps1",
            ],
            "env": {"JARVIS_CI_PROFILE": "msi-operational"},
        }
    ]


def test_write_marker_suppressed_by_flag(tmp_path):
    assert ci.write_marker(tmp_path, "pass", no_mark=True) is False
    assert not (tmp_path / ".agentready" / "gate_status.json").exists()


def test_write_marker_suppressed_by_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTREADY_CI_NO_MARK", "1")
    assert ci.write_marker(tmp_path, "pass") is False
    assert not (tmp_path / ".agentready" / "gate_status.json").exists()


def test_run_no_entrypoints(tmp_path, capsys):
    (tmp_path / "README.md").write_text("x", encoding="utf-8")
    result = ci.run(tmp_path, echo=False, write_outputs=False)
    assert result["steps_run"] == 0
    assert result["gate_status"] == "fail"
    assert result["exit_code"] == 0
    assert "WARN no known CI/test entrypoints detected" in result["log"]
