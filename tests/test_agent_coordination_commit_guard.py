from __future__ import annotations

import subprocess

import pytest

import agent_runtime_paths
from agent_coordination import commit_guard, tasks
from agent_coordination import memory_compliance as mc


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_runtime_paths, "COORDINATION_ROOT", tmp_path / "coordination")
    monkeypatch.delenv("AGENTREADY_COMMIT_OVERRIDE", raising=False)
    r = tmp_path / "proj"
    r.mkdir()
    subprocess.run(["git", "init"], cwd=str(r), capture_output=True, check=True)
    return r


def _claim(repo, **over):
    t = {"id": "t1", "title": "do work", "status": "in_progress", "agent": "claude",
         "summary": "a sufficiently long intent summary", "paths": ["src/a.py"]}
    t.update(over)
    tasks.write_task(repo, t)


def test_no_staged_paths_allows(repo):
    v = commit_guard.evaluate(repo, paths=[], agent="claude")
    assert v["verdict"] == "allow" and v["exit_code"] == 0 and v["reason"] == "no_paths"


def test_ungoverned_repo_allows(repo):
    # no claim/store written -> tasks dir absent -> ungoverned -> allow
    v = commit_guard.evaluate(repo, paths=["src/a.py"], agent="claude")
    assert v["verdict"] == "allow" and v["reason"] == "ungoverned"


def test_internal_enforcement_error_blocks(repo, monkeypatch):
    monkeypatch.setattr(commit_guard, "resolve_repo", lambda _repo: (_ for _ in ()).throw(OSError("broken state")))
    v = commit_guard.evaluate(repo, paths=["src/a.py"], agent="claude")
    assert v["verdict"] == "block"
    assert v["exit_code"] == 2
    assert v["reason"] == "enforcement_error"
    assert "broken state" in v["error"]


def test_unreadable_staged_state_blocks(repo, monkeypatch):
    _claim(repo)

    def broken_run(*_args, **_kwargs):
        raise OSError("git unavailable")

    monkeypatch.setattr(commit_guard.subprocess, "run", broken_run)
    v = commit_guard.evaluate(repo, paths=None, agent="claude")
    assert v["verdict"] == "block"
    assert v["reason"] == "enforcement_error"
    assert "git unavailable" in v["error"]


def test_covered_path_allows(repo):
    _claim(repo)
    v = commit_guard.evaluate(repo, paths=["src/a.py"], agent="claude")
    assert v["verdict"] == "allow" and v["reason"] == "ok"


def test_required_memory_receipts_block_commit_until_compliant(repo):
    _claim(repo, memory_compliance=mc.new_policy())
    blocked = commit_guard.evaluate(repo, paths=["src/a.py"], agent="claude")
    assert blocked["verdict"] == "block"
    assert blocked["memory_failures"]
    task = tasks.read_task(repo, "t1")
    mc.append_receipt(task, mc.build_receipt(
        "t1", kind="graph_query", agent="claude", query="commit guard",
        evidence="factory-memory-graph query receipt",
    ))
    mc.append_receipt(task, mc.build_receipt(
        "t1", kind="serena_read", agent="claude", store="serena-factory",
        memory_name="global/factory-doctrine-and-protocols", evidence="Serena read receipt",
    ))
    tasks.write_task(repo, task)
    assert commit_guard.evaluate(repo, paths=["src/a.py"], agent="claude")["verdict"] == "allow"


def test_uncovered_path_blocks(repo):
    _claim(repo, paths=["src/b.py"])
    v = commit_guard.evaluate(repo, paths=["src/a.py"], agent="claude")
    assert v["verdict"] == "block" and v["exit_code"] == 1 and v["uncovered"] == ["src/a.py"]


def test_wrong_agent_does_not_cover(repo):
    _claim(repo, agent="codex")
    v = commit_guard.evaluate(repo, paths=["src/a.py"], agent="claude")
    assert v["verdict"] == "block"


def test_empty_summary_does_not_cover(repo):
    _claim(repo, summary="")
    v = commit_guard.evaluate(repo, paths=["src/a.py"], agent="claude")
    assert v["verdict"] == "block"


def test_protected_path_without_intent_blocks(repo):
    _claim(repo, paths=["tests/x.py"], title="add feature", summary="implement the product change now")
    v = commit_guard.evaluate(repo, paths=["tests/x.py"], agent="claude")
    assert v["verdict"] == "block" and v["protected_failures"] and "protected" in v["protected_failures"][0].lower()


def test_protected_path_with_intent_allows(repo):
    _claim(repo, paths=["tests/x.py"], title="add regression test", summary="test coverage for the gate")
    v = commit_guard.evaluate(repo, paths=["tests/x.py"], agent="claude")
    assert v["verdict"] == "allow"


def test_override_allows_and_is_recorded(repo):
    _claim(repo, paths=["src/b.py"])  # would otherwise block
    v = commit_guard.evaluate(repo, paths=["src/a.py"], agent="claude", override="emergency hotfix")
    assert v["verdict"] == "allow" and v["reason"] == "override"


def test_cli_block_exit_code_and_message(repo, capsys, monkeypatch):
    _claim(repo, paths=["src/b.py"])
    monkeypatch.setenv("AGENTREADY_AGENT", "claude")
    rc = commit_guard.main(["--repo", str(repo), "--paths", "src/a.py"])
    out = capsys.readouterr().out
    assert rc == 1 and "BLOCKED by the Factory commit-guard" in out and "src/a.py" in out


def test_cli_ok_exit_zero(repo, capsys, monkeypatch):
    _claim(repo)
    monkeypatch.setenv("AGENTREADY_AGENT", "claude")
    rc = commit_guard.main(["--repo", str(repo), "--paths", "src/a.py"])
    assert rc == 0 and "OK - all staged paths covered" in capsys.readouterr().out
