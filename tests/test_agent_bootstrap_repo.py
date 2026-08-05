# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Focused tests for portable repository bootstrap behavior."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import agent_bootstrap_repo as b  # noqa: E402


# --------------------------------------------------------------------------- set_marked_block
def test_set_marked_block_new_file(tmp_path):
    p = tmp_path / "AGENTS.md"
    b.set_marked_block(p, "AgentReady Local Stack", ["", "line one", ""])
    text = p.read_text(encoding="utf-8")
    assert text.startswith(b.MARKER_START)
    assert "# AgentReady Local Stack" in text and "line one" in text
    assert text.rstrip("\r\n").endswith(b.MARKER_END)


def test_set_marked_block_idempotent_without_force(tmp_path):
    p = tmp_path / "AGENTS.md"
    b.set_marked_block(p, "T", ["original"])
    before = p.read_text(encoding="utf-8")
    b.set_marked_block(p, "T", ["CHANGED"])  # no force -> unchanged
    assert p.read_text(encoding="utf-8") == before
    assert "CHANGED" not in p.read_text(encoding="utf-8")


def test_set_marked_block_force_replaces(tmp_path):
    p = tmp_path / "AGENTS.md"
    b.set_marked_block(p, "T", ["original"])
    b.set_marked_block(p, "T", ["replaced"], force=True)
    text = p.read_text(encoding="utf-8")
    assert "replaced" in text and "original" not in text


def test_set_marked_block_appends_when_no_marker(tmp_path):
    p = tmp_path / "AGENTS.md"
    p.write_text("# Existing content\n", encoding="utf-8")
    b.set_marked_block(p, "T", ["appended"])
    text = p.read_text(encoding="utf-8")
    assert "# Existing content" in text and b.MARKER_START in text and "appended" in text


# --------------------------------------------------------------------------- add_unique_line
def test_add_unique_line(tmp_path):
    p = tmp_path / ".gitignore"
    b.add_unique_line(p, ".agent-reports/")
    b.add_unique_line(p, ".agent-reports/")  # dup -> not added twice
    b.add_unique_line(p, ".agent-state/worktrees/")
    lines = p.read_text(encoding="utf-8").replace("\r\n", "\n").rstrip("\n").split("\n")
    assert lines == [".agent-reports/", ".agent-state/worktrees/"]


# --------------------------------------------------------------------------- bootstrap
def test_bootstrap_creates_scaffolding_and_calls_init(tmp_path):
    repo = tmp_path / "repo"
    calls = []
    result = b.bootstrap(repo, template_root=tmp_path / "no-templates",
                         coordination_init_fn=lambda r: calls.append(str(r)))
    assert calls == [str(repo)]  # coordination-init invoked once
    for rel in ("AGENTS.md", ".gitignore", ".agentready.yaml"):
        assert (repo / rel).exists(), rel
    agents = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "agentready tool-router --task" in agents and b.MARKER_START in agents
    yaml = (repo / ".agentready.yaml").read_text(encoding="utf-8")
    assert "version: 1" in yaml and "required_final_audit: agentready release-scorecard" in yaml
    assert ".agent-state" in result["files"]


def test_router_lines_contract():
    # The generated instructions retain routing, release, and handoff guidance.
    joined = "\n".join(b.ROUTER_LINES)
    assert "auditable" in joined
    assert 'agentready tool-router --task "<user request>" --mode plan' in joined
    assert "agentready release-scorecard --repo ." in joined
    assert "agentready coordination task-start" in joined
    assert "interpreted evidence" in joined
    assert "Act as an engineering operator, not a narrator" in joined
    assert "agentready session-reentry issue" in joined
    assert "DONE means the applicable gate is green for the exact commit" in joined


def test_default_coordination_init_uses_public_console_command(monkeypatch, tmp_path):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(b.subprocess, "run", fake_run)
    b._default_coordination_init(tmp_path)
    assert calls[0][0] == [
        b.sys.executable,
        "-m",
        "agent_coordination.cli",
        "coordination-init",
        "--repo",
        str(tmp_path),
    ]


def test_default_coordination_init_propagates_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(
        b.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(command, 7, stdout="", stderr="blocked"),
    )
    with pytest.raises(RuntimeError, match="coordination initialization failed"):
        b._default_coordination_init(tmp_path)
