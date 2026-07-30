# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Initialize a repository with portable AgentReady guidance and empty local state.

The bootstrap writes an idempotent instruction block to ``AGENTS.md``, adds
generated-state exclusions to ``.gitignore``, creates a provider-neutral
``.agentready.yaml``, and invokes the installed coordination initializer when
available. It never copies credentials, contacts a remote service, or starts a
listener.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

MARKER_START = "<!-- AGENTREADY:START -->"
MARKER_END = "<!-- AGENTREADY:END -->"
NEWLINE = os.linesep

ROUTER_LINES = [
    "",
    "Use AgentReady before meaningful repository work so intent, ownership, evidence, and handoffs remain "
    "auditable.",
    "",
    "Meaningful work includes broad repo reads, code edits, tests, reviews, dependency changes, runtime "
    "checks, packaging, release-readiness work, cleanup, architecture analysis, and handoffs.",
    "",
    "Before broad repo reads, code edits, dependency changes, security work, packaging, release-readiness "
    "claims, or full-stack delivery work:",
    "",
    "```text",
    'agentready tool-router --task "<user request>" --mode plan',
    "```",
    "",
    "Before final delivery claims:",
    "",
    "```powershell",
    "agentready tool-router --profile release --mode run --include-heavy",
    "agentready tool-router --profile release --mode audit",
    "agentready release-scorecard --repo .",
    "```",
    "",
    "For multi-agent or large-repository work:",
    "",
    "```powershell",
    "agentready coordination coordination-init --repo .",
    "agentready coordination task-status --repo .",
    'agentready tool-router --task "<what this model intends to do>" --mode plan',
    'agentready coordination task-start --repo . --title "<clear task title>" --agent "<agent-id>" '
    '--summary "<intent and current scope>" --paths "<paths>" --create-worktree',
    'agentready coordination conflict-check --repo . --task-id "<task-id>"',
    'agentready coordination task-handoff --repo . --task-id "<task-id>" --operator "<operator-id>" '
    '--summary "<what changed/current state>" --evidence "<interpreted test/evidence summary>" '
    '--next "<next safe action or none remains>"',
    "```",
    "",
    "Do not silently skip relevant AgentReady tools. If a relevant tool was not run, state why. Use "
    "`.agent-state` as the local coordination truth.",
    "",
    "No model may leave this repo with less shared resolution than it had on entry. Preserve current HEAD, "
    "evidence quality, dirty tree posture, blockers, live/runtime state, and next safe actions before "
    "handoff or token exhaustion.",
    "",
    "Coordination commands enforce quality gates: task starts require a meaningful summary and claimed "
    "paths; handoffs require interpreted evidence and a clear next action.",
]

AGENTREADY_YAML = NEWLINE.join([
    "version: 1",
    "router: agentready tool-router",
    "required_final_audit: agentready release-scorecard",
    "coordination:",
    "  init: agentready coordination coordination-init",
    "  task_start: agentready coordination task-start",
    "  task_status: agentready coordination task-status",
    "  handoff: agentready coordination task-handoff",
    "  conflict_check: agentready coordination conflict-check",
    "reports_dir: .agent-reports",
    "state_dir: .agent-state",
]) + NEWLINE


def add_unique_line(path: Path, line: str) -> None:
    """Port of `Add-UniqueLine`: append a line only if not already present."""
    existing = (path.read_text(encoding="utf-8-sig", errors="replace").replace("\r\n", "\n").split("\n")
                if path.exists() else [])
    if line not in existing:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="") as fh:
            fh.write(line + NEWLINE)


def set_marked_block(path: Path, title: str, lines: list[str], force: bool = False) -> None:
    """Port of `Set-MarkedBlock`: write/replace the AGENTREADY marked block (idempotent unless force)."""
    block = NEWLINE.join([MARKER_START, f"# {title}", *lines, MARKER_END])
    new_text = block + NEWLINE
    if path.exists():
        existing = path.read_text(encoding="utf-8-sig", errors="replace")
        pattern = re.escape(MARKER_START) + r".*?" + re.escape(MARKER_END)
        if re.search(pattern, existing, flags=re.DOTALL):
            if force:
                updated = re.sub(pattern, lambda _m: block, existing, flags=re.DOTALL)
                path.write_text(updated, encoding="utf-8", newline="")
            return
        with path.open("a", encoding="utf-8", newline="") as fh:
            fh.write(NEWLINE + new_text)
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_text, encoding="utf-8", newline="")


def _default_coordination_init(repo: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "agent_coordination.cli", "coordination-init", "--repo", str(repo)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        raise RuntimeError(f"coordination initialization failed ({result.returncode}): {detail}")


def bootstrap(repo: Path, *, force: bool = False, template_root: Path | None = None,
              coordination_init_fn=None) -> dict:
    """Create portable configuration and empty coordination state in ``repo``.

    ``template_root`` remains accepted for backward API compatibility but is
    intentionally unused: public bootstrap output is generated locally.
    """
    del template_root
    repo = Path(repo)
    repo.mkdir(parents=True, exist_ok=True)

    set_marked_block(repo / "AGENTS.md", "AgentReady Local Stack", ROUTER_LINES, force=force)
    add_unique_line(repo / ".gitignore", ".agent-reports/")
    add_unique_line(repo / ".gitignore", ".agent-state/worktrees/")

    yaml_path = repo / ".agentready.yaml"
    if force or not yaml_path.exists():
        yaml_path.write_text(AGENTREADY_YAML, encoding="utf-8", newline="")

    (coordination_init_fn or _default_coordination_init)(repo)
    return {"repo": str(repo),
            "files": ["AGENTS.md", ".gitignore", ".agentready.yaml", ".agent-state"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser("agent_bootstrap_repo")
    parser.add_argument("-Repo", "--repo", default=os.getcwd())
    parser.add_argument("-Force", "--force", action="store_true")
    args = parser.parse_args(argv)
    result = bootstrap(Path(args.repo), force=args.force)
    print(f"AgentReady repo bootstrap complete: {result['repo']}")
    print("Added/verified AGENTS.md, .gitignore, .agentready.yaml, and empty .agent-state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
