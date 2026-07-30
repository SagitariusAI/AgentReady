"""Python unit tests for agent_coordination.paths (the ported claim/guard matching brain).

Distinct from tests/test_agent_coordination_paths.py, which drives the *PowerShell* library directly —
that one remains the live parity check against the .ps1 until the lib is retired (Phase 7). This file
asserts the Python port satisfies the same behavioral contract.
"""
from __future__ import annotations

import subprocess

import pytest

import agent_runtime_paths
from agent_coordination import paths, tasks


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_runtime_paths, "COORDINATION_ROOT", tmp_path / "coordination")
    r = tmp_path / "proj"
    r.mkdir()
    subprocess.run(["git", "init"], cwd=str(r), capture_output=True, check=True)
    return r


def test_to_path_list_splits_comma_joined_string():
    # the critical non-PowerShell-caller invariant (matches the PS-driving regression test)
    assert paths.to_path_list("a.py,b.py,c.py") == ["a.py", "b.py", "c.py"]
    assert paths.to_path_list("a.py, b.py ,  c.py") == ["a.py", "b.py", "c.py"]
    assert paths.to_path_list("a.py,,b.py,") == ["a.py", "b.py"]
    assert paths.to_path_list(["src\\pkg\\mod.py", "tests\\t.py"]) == ["src/pkg/mod.py", "tests/t.py"]
    assert paths.to_path_list(None) == [] and paths.to_path_list([]) == []


def test_path_overlap_parent_equal_and_blob():
    assert paths.path_overlap("src/a.py", "src/a.py") is True
    assert paths.path_overlap("src", "src/a.py") is True
    assert paths.path_overlap("src/a.py", "src") is True
    assert paths.path_overlap("src/a.py", "src/b.py") is False
    assert paths.path_overlap("srcx", "src") is False
    # the pre-fix blob never matches an individual file
    assert paths.path_overlap("a.py,b.py,c.py", "b.py") is False


def test_protected_surface_categories():
    doctrine = paths.protected_surface("docs/AGENT_CONSTITUTION.md")
    gate = paths.protected_surface("bin/agent-commit-guard.ps1")
    test = paths.protected_surface("tests/test_x.py")
    manifest = paths.protected_surface("pyproject.toml")
    assert doctrine is not None and doctrine["category"] == "doctrine"
    assert gate is not None and gate["category"] == "gate"
    assert test is not None and test["category"] == "test"
    assert manifest is not None and manifest["category"] == "manifest"
    assert paths.protected_surface("src/app.py") is None


def test_protected_path_intent_requires_matching_words():
    issues = paths.protected_path_intent(["docs/AGENT_CONSTITUTION.md"],
                                         title="Finish feature implementation",
                                         summary="Implement the requested product change.")
    assert len(issues) == 1 and "doctrine" in issues[0].lower() and "protected" in issues[0].lower()
    assert paths.protected_path_intent(["docs/AGENT_CONSTITUTION.md"],
                                       title="Harden Factory governance doctrine", summary="policy") == []


def test_path_conflicts_against_active_claims(repo):
    tasks.write_task(repo, {"id": "t1", "title": "x", "status": "in_progress", "agent": "codex",
                            "paths": ["src/foundry.py"]})
    conflicts = paths.path_conflicts(repo, ["src/foundry.py", "src/other.py"])
    assert len(conflicts) == 1 and conflicts[0]["task_id"] == "t1"
    assert paths.path_conflicts(repo, ["src/foundry.py"], exclude_task_id="t1") == []
    # inactive task -> no conflict
    tasks.write_task(repo, {"id": "done", "status": "complete", "paths": ["src/x.py"]})
    assert paths.path_conflicts(repo, ["src/x.py"]) == []
