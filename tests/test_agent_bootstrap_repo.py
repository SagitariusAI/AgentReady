"""Focused tests for the repo-bootstrap durable logic (PS->Python Phase 7)."""
from __future__ import annotations

import sys
from pathlib import Path

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
    for rel in ("AGENTS.md", "CLAUDE.md", ".gitignore", ".agentready.yaml"):
        assert (repo / rel).exists(), rel
    agents = (repo / "AGENTS.md").read_text(encoding="utf-8")
    assert "agent-tool-router -Task" in agents and b.MARKER_START in agents
    yaml = (repo / ".agentready.yaml").read_text(encoding="utf-8")
    assert "version: 1" in yaml and "required_final_audit: agent-release-scorecard" in yaml
    assert ".agent-state" in result["files"]


def test_router_lines_contract():
    # the marked-block instructions must keep the strict-entry + router + handoff guidance
    joined = "\n".join(b.ROUTER_LINES)
    assert "strict-entry workspaces" in joined
    assert 'agent-tool-router -Task "<user request>" -Mode Plan' in joined
    assert "agent-release-scorecard" in joined
    assert "-AllowWeak only for an explicitly weak/emergency record" in joined
