# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Fleet deployment and health reporting for per-repository Factory Capture.

The capture runtime is repo-scoped, but AgentReady owns the managed-project
registry. This module closes that deployment gap without inventing another
registry: it initializes capture stores and installs the existing non-blocking
git hooks for every active, locally available Git repository declared there.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from factory_capture.common import now_iso, write_json
from factory_capture.events import append_event, count_events, last_events, new_event
from factory_capture.gitstate import capture_git_state
from factory_capture.hooks import hooks_state, install_hooks
from factory_capture.store import Store

LOCAL_EXCLUDE_ENTRY = "/.factory_capture/"


def _default_agentready_home() -> Path:
    configured = os.environ.get("AGENTREADY_HOME")
    return Path(configured) if configured else Path(__file__).resolve().parents[2]


def _project_entries(agentready_home: Path) -> list[dict[str, Any]]:
    registry = agentready_home / "data" / "project-registry" / "projects"
    entries: list[dict[str, Any]] = []
    if not registry.exists():
        return entries
    for path in sorted(registry.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, dict) and payload.get("status") == "active":
            entries.append(payload)
    return entries


def _project_root(project: dict[str, Any]) -> str:
    raw_paths = project.get("paths")
    paths = raw_paths if isinstance(raw_paths, dict) else {}
    root_key = str(project.get("topology_root_key") or "")
    return str(paths.get(root_key) or "") if root_key else ""


def _repo_status(project: dict[str, Any]) -> dict[str, Any]:
    raw_root = _project_root(project)
    row: dict[str, Any] = {
        "project_id": str(project.get("id") or ""),
        "project_name": str(project.get("name") or ""),
        "declared_root": raw_root,
        "eligibility": "",
        "initialized": False,
        "hooks": {},
        "hooks_complete": False,
        "event_count": 0,
        "last_event": None,
    }
    if not raw_root or raw_root.startswith("/"):
        row["eligibility"] = "unavailable_in_windows_lane"
        return row
    root = Path(raw_root)
    if not root.exists():
        row["eligibility"] = "missing"
        return row
    if not (root / ".git").exists():
        row["eligibility"] = "not_git"
        return row

    row["eligibility"] = "eligible_git_repo"
    store = Store(root / ".factory_capture")
    row["initialized"] = store.exists()
    row["hooks"] = hooks_state(root)
    row["hooks_complete"] = bool(row["hooks"]) and all(row["hooks"].values())
    if store.exists():
        row["event_count"] = count_events(store)
        latest = last_events(store, 1)
        row["last_event"] = latest[-1] if latest else None
    return row


def _ensure_local_exclude(repo_root: Path) -> None:
    """Keep the repo-local evidence store out of Git without editing tracked files."""
    exclude = repo_root / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
    entries = {line.strip() for line in existing.splitlines()}
    if LOCAL_EXCLUDE_ENTRY in entries:
        return
    separator = "" if not existing or existing.endswith("\n") else "\n"
    exclude.write_text(
        f"{existing}{separator}{LOCAL_EXCLUDE_ENTRY}\n",
        encoding="utf-8",
    )


def _summary(projects: list[dict[str, Any]]) -> dict[str, int]:
    eligible = [row for row in projects if row["eligibility"] == "eligible_git_repo"]
    return {
        "active_projects": len(projects),
        "eligible_git_repos": len(eligible),
        "initialized_repos": sum(1 for row in eligible if row["initialized"]),
        "fully_hooked_repos": sum(1 for row in eligible if row["hooks_complete"]),
        "unavailable_projects": sum(1 for row in projects if row["eligibility"] in {"missing", "unavailable_in_windows_lane"}),
        "non_git_projects": sum(1 for row in projects if row["eligibility"] == "not_git"),
        "captured_events": sum(int(row["event_count"]) for row in eligible),
    }


def _write_report(agentready_home: Path, payload: dict[str, Any]) -> None:
    report_root = agentready_home / "reports" / "factory-capture-fleet"
    write_json(report_root / "latest.json", payload)
    summary = payload["summary"]
    lines = [
        "# Factory Capture Fleet",
        "",
        f"- Generated: `{payload['generated_at']}`",
        f"- Status: `{payload['status']}`",
        f"- Eligible Git repositories: `{summary['eligible_git_repos']}`",
        f"- Initialized repositories: `{summary['initialized_repos']}`",
        f"- Fully hooked repositories: `{summary['fully_hooked_repos']}`",
        f"- Captured events: `{summary['captured_events']}`",
        f"- Unavailable projects: `{summary['unavailable_projects']}`",
        f"- Non-Git projects: `{summary['non_git_projects']}`",
        "",
        "| Project | Eligibility | Store | Hooks | Events |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in payload["projects"]:
        lines.append(
            f"| {row['project_name']} | `{row['eligibility']}` | "
            f"`{row['initialized']}` | `{row['hooks_complete']}` | `{row['event_count']}` |"
        )
    report_root.mkdir(parents=True, exist_ok=True)
    (report_root / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def fleet_status(agentready_home: Path | str | None = None) -> dict[str, Any]:
    home = Path(agentready_home) if agentready_home else _default_agentready_home()
    projects = [_repo_status(project) for project in _project_entries(home)]
    summary = _summary(projects)
    complete = (
        summary["eligible_git_repos"] > 0
        and summary["initialized_repos"] == summary["eligible_git_repos"]
        and summary["fully_hooked_repos"] == summary["eligible_git_repos"]
    )
    payload = {
        "schema_version": "factory_capture.fleet.v1",
        "generated_at": now_iso(),
        "status": "PASS" if complete else "FAIL",
        "summary": summary,
        "projects": projects,
    }
    _write_report(home, payload)
    return payload


def deploy_fleet(agentready_home: Path | str | None = None) -> dict[str, Any]:
    home = Path(agentready_home) if agentready_home else _default_agentready_home()
    for project in _project_entries(home):
        raw_root = _project_root(project)
        if not raw_root or raw_root.startswith("/"):
            continue
        root = Path(raw_root)
        if not root.exists() or not (root / ".git").exists():
            continue
        _ensure_local_exclude(root)
        store = Store(root / ".factory_capture")
        init_result = store.init(repo_root=root)
        install_hooks(root, source_root=home / "src")
        if init_result["created"]:
            append_event(
                store,
                new_event(
                    "session_start",
                    repo_root=str(root),
                    cwd=str(root),
                    command=["factory-capture", "fleet", "deploy"],
                    git_after=capture_git_state(root),
                    text="AgentReady fleet deployment initialized repository capture.",
                ),
            )
    return fleet_status(home)
