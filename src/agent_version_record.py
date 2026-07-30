# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Public support for agent version record."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from agent_coordination.events import add_event
from agent_coordination.store import ensure_state, resolve_repo

_EVIDENCE_DIRS = (".agent-reports\\release-scorecard", ".agent-reports\\release-readiness",
                  ".agent-reports\\sbom", ".agent-reports\\package-windows")


def _git(repo: Path, *args: str) -> str:
    try:
        out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                             timeout=20, check=False)
        return out.stdout
    except Exception:  # noqa: BLE001
        return ""


def build_manifest(*, version: str, repo: str, task_id: str, agent: str, summary: str, git_head: str,
                   git_status: list[str], created_at: str) -> dict:
    return {"version": version, "repo": repo, "task_id": task_id, "agent": agent, "summary": summary,
            "git_head": git_head, "git_status": git_status, "created_at": created_at,
            "scorecard": ".agent-reports/release-scorecard/latest.md",
            "release_readiness": ".agent-reports/release-readiness", "sbom": ".agent-reports/sbom",
            "package": ".agent-reports/package-windows"}


def render_md(manifest: dict) -> str:
    return "\n".join([
        f"# Version Record: {manifest['version']}", "",
        f"- Repo: {manifest['repo']}",
        f"- Task: {manifest['task_id']}",
        f"- Agent: {manifest['agent']}",
        f"- Git head: {manifest['git_head']}",
        f"- Created: {manifest['created_at']}", "",
        "## Summary", "", manifest["summary"], "",
        "## Evidence", "",
        "- `.agent-reports/release-scorecard/latest.md`",
        "- `.agent-reports/release-readiness`",
        "- `.agent-reports/sbom`",
        "- `.agent-reports/package-windows`"])


def run(*, repo: str, version: str, agent: str = "", summary: str = "", task_id: str = "",
        copy_evidence: bool = False, add_event_fn=None) -> dict:
    repo_root = resolve_repo(repo)
    state = ensure_state(repo_root)
    version_dir = state / "versions" / version
    version_dir.mkdir(parents=True, exist_ok=True)

    head = _git(repo_root, "log", "-1", "--oneline").strip()
    status = [ln for ln in _git(repo_root, "status", "--short").replace("\r\n", "\n").split("\n") if ln]
    created_at = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    manifest = build_manifest(version=version, repo=str(repo_root), task_id=task_id, agent=agent,
                              summary=summary, git_head=head, git_status=status, created_at=created_at)
    (version_dir / "release-manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (version_dir / "release-manifest.md").write_text(render_md(manifest), encoding="utf-8")

    if copy_evidence:
        evidence_dir = version_dir / "evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)
        for rel in _EVIDENCE_DIRS:
            src = repo_root / rel.replace("\\", os.sep)
            if src.exists():
                shutil.copytree(src, evidence_dir / Path(rel).name, dirs_exist_ok=True)

    if task_id:
        (add_event_fn or add_event)(repo_root, task_id, "version_recorded", agent=agent, message=version,
                                    data={"version": version,
                                          "manifest": str(version_dir / "release-manifest.json")})
    return {"version_dir": version_dir, "manifest": manifest}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser("agent_version_record")
    parser.add_argument("-Repo", "--repo", default=os.getcwd())
    parser.add_argument("-Version", "--version", required=True)
    parser.add_argument("-Agent", "--agent", default=os.environ.get("USERNAME", ""))
    parser.add_argument("-Summary", "--summary", default="")
    parser.add_argument("-TaskId", "--task-id", default="")
    parser.add_argument("-CopyEvidence", "--copy-evidence", action="store_true")
    args = parser.parse_args(argv)
    result = run(repo=args.repo, version=args.version, agent=args.agent, summary=args.summary,
                 task_id=args.task_id, copy_evidence=args.copy_evidence)
    print(f"Agent version record written: {result['version_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
