"""Focused tests for the coordination-lib consumer ports: history-search + version-record (Phase 7f)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import agent_history_search as hs  # noqa: E402
import agent_runtime_paths as arp  # noqa: E402
import agent_version_record as vr  # noqa: E402
from agent_coordination.store import ensure_state  # noqa: E402


def _repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    for a in (["init", "-q"], ["config", "user.email", "t@e"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True)
    (repo / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "init"], check=True, capture_output=True)
    return repo


# --------------------------------------------------------------------------- history-search
def test_history_search_finds_and_misses(tmp_path, monkeypatch):
    monkeypatch.setattr(arp, "COORDINATION_ROOT", tmp_path / "coord")
    repo = _repo(tmp_path)
    state = ensure_state(repo)
    (state / "tasks" / "t1.json").write_text(json.dumps({"id": "t1", "title": "FINDME widget"}),
                                             encoding="utf-8")
    hits = hs.run(repo=str(repo), query="FINDME")["results"]
    assert any("FINDME" in line for line in hits)
    assert hs.run(repo=str(repo), query="ZZZ-NO-MATCH")["results"] == []


def test_history_search_stub_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(arp, "COORDINATION_ROOT", tmp_path / "coord")
    repo = _repo(tmp_path)
    state = ensure_state(repo)
    (state / "events" / "e.jsonl").parent.mkdir(parents=True, exist_ok=True)
    (state / "events" / "e.jsonl").write_text("alpha NEEDLE beta\n", encoding="utf-8")
    # force the stdlib fallback (no rg) via an injected search_fn that mimics the grep path
    out = hs.search(state, "NEEDLE", search_fn=lambda s, q: [f"{p}:{q}" for p in s.rglob("*")
                                                             if p.is_file() and q in p.read_text(
                                                                 encoding="utf-8", errors="replace")])
    assert any("NEEDLE" in line for line in out)


# --------------------------------------------------------------------------- version-record
def test_version_record_manifest_and_event(tmp_path, monkeypatch):
    monkeypatch.setattr(arp, "COORDINATION_ROOT", tmp_path / "coord")
    repo = _repo(tmp_path)
    events = []
    res = vr.run(repo=str(repo), version="v9.9.9", agent="claude", summary="the release", task_id="t1",
                 add_event_fn=lambda *a, **k: events.append((a, k)))
    vd = res["version_dir"]
    manifest = json.loads((vd / "release-manifest.json").read_text())
    assert list(manifest) == ["version", "repo", "task_id", "agent", "summary", "git_head", "git_status",
                              "created_at", "scorecard", "release_readiness", "sbom", "package"]
    assert manifest["version"] == "v9.9.9" and manifest["agent"] == "claude"
    assert manifest["scorecard"] == ".agent-reports/release-scorecard/latest.md"
    md = (vd / "release-manifest.md").read_text()
    assert "# Version Record: v9.9.9" in md and "## Summary\n\nthe release" in md
    assert "- `.agent-reports/sbom`" in md
    assert len(events) == 1 and events[0][0][1:3] == ("t1", "version_recorded")


def test_version_record_no_event_without_task(tmp_path, monkeypatch):
    monkeypatch.setattr(arp, "COORDINATION_ROOT", tmp_path / "coord")
    repo = _repo(tmp_path)
    events = []
    vr.run(repo=str(repo), version="v1", add_event_fn=lambda *a, **k: events.append(a))
    assert events == []  # no -TaskId -> no event


def test_version_record_render_md_template():
    m = vr.build_manifest(version="v1", repo="D:/R", task_id="", agent="a", summary="s", git_head="abc123",
                          git_status=["M x"], created_at="2026-06-18T00:00:00")
    md = vr.render_md(m)
    assert md.splitlines()[0] == "# Version Record: v1"
    assert "- Git head: abc123" in md and "- Created: 2026-06-18T00:00:00" in md
