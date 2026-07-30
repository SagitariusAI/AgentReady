"""Repo bootstrap -- Python port of `bin/agent-bootstrap-repo.ps1` (PS->Python Phase 7).

Scaffolds a repo for the AgentReady stack: writes the `<!-- AGENTREADY:START/END -->` marked block (the
router/coordination instructions) into AGENTS.md + CLAUDE.md, appends the two machine-local `.gitignore`
lines, copies the Forgejo CI workflow + release checklist from the templates, writes `.agentready.yaml`,
and runs `agent-coordination-init`. Idempotent: an existing marked block is left as-is unless `-Force`;
template/yaml copies only fill gaps unless `-Force`.

The marked block + yaml are CRLF-joined (`[Environment]::NewLine`) and written verbatim (`newline=""`) to
match the PowerShell output (the BOM PowerShell 5.1 added is dropped, matching the rest of the migration).
`agent-coordination-init` is an injectable seam. Parity:
`smoke/agent_bootstrap_repo_parity_smoke.py` compares the generated files against the real PS bootstrap on
a temp repo.
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path

AGENTREADY_HOME = Path(os.environ.get("AGENTREADY_HOME") or Path(__file__).resolve().parents[1])
TEMPLATE_ROOT = AGENTREADY_HOME / "templates" / "repo"
MARKER_START = "<!-- AGENTREADY:START -->"
MARKER_END = "<!-- AGENTREADY:END -->"
NEWLINE = "\r\n"  # [Environment]::NewLine on Windows

ROUTER_LINES = [
    "",
    "Founder-claimed project repos are strict-entry workspaces. No model may perform meaningful repo work "
    "without logging clear intent in AgentReady first.",
    "",
    "Meaningful work includes broad repo reads, code edits, tests, reviews, dependency changes, runtime "
    "checks, packaging, release-readiness work, cleanup, architecture analysis, and handoffs.",
    "",
    "Before broad repo reads, code edits, dependency changes, security work, packaging, release-readiness "
    "claims, or full-stack delivery work:",
    "",
    "```powershell",
    ". D:\\AgentReady\\bin\\agent-tool-env.ps1",
    'agent-tool-router -Task "<user request>" -Mode Plan',
    "```",
    "",
    "Before final delivery claims:",
    "",
    "```powershell",
    "agent-tool-router -Profile release -Mode Run -IncludeHeavy",
    "agent-tool-router -Profile release -Mode Audit",
    "agent-release-scorecard",
    "```",
    "",
    "For multi-agent, large-repo, or founder-claimed project work:",
    "",
    "```powershell",
    "agent-coordination-init",
    "agent-task-status",
    'agent-tool-router -Task "<what this model intends to do>" -Mode Plan',
    'agent-task-start -Title "<clear task title>" -Agent "<codex|claude|forge|other>" -Summary "<intent '
    'and current scope>" -Paths <paths> -CreateWorktree',
    "agent-conflict-check -TaskId <task-id>",
    'agent-task-handoff -TaskId <task-id> -Operator "<windows-user>" -Summary "<what changed/current '
    'state>" -Evidence "<interpreted test/evidence summary>" -Next "<next safe action or none remains>"',
    "```",
    "",
    "Do not silently skip relevant AgentReady tools. If a relevant tool was not run, state why. Use "
    "`.agent-state` as the local coordination truth.",
    "",
    "No model may leave this repo with less shared resolution than it had on entry. Preserve current HEAD, "
    "evidence quality, dirty tree posture, blockers, live/runtime state, and next safe actions before "
    "handoff or token exhaustion.",
    "",
    "Normal AgentReady coordination commands enforce quality gates: task starts require a meaningful "
    "summary and claimed paths; handoffs require summary, claimed paths, interpreted evidence, and next "
    "action. Use -AllowWeak only for an explicitly weak/emergency record and say why it is weak.",
]

AGENTREADY_YAML = NEWLINE.join([
    "version: 1",
    "stack_index: D:\\AgentReady\\AGENT_READY_STACK_INDEX.md",
    "router: agent-tool-router",
    "required_final_audit: agent-release-scorecard",
    "coordination:",
    "  init: agent-coordination-init",
    "  task_start: agent-task-start",
    "  task_status: agent-task-status",
    "  handoff: agent-task-handoff",
    "  conflict_check: agent-conflict-check",
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


def _copy_if_gap(src: Path, dest: Path, force: bool) -> None:
    if force or not dest.exists():
        if src.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)


def _default_coordination_init(repo: Path) -> None:
    try:
        subprocess.run(["agent-coordination-init", "-Repo", str(repo)], capture_output=True, text=True,
                       timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        return


def bootstrap(repo: Path, *, force: bool = False, template_root: Path | None = None,
              coordination_init_fn=None) -> dict:
    repo = Path(repo)
    template_root = template_root or TEMPLATE_ROOT
    repo.mkdir(parents=True, exist_ok=True)

    set_marked_block(repo / "AGENTS.md", "AgentReady Local Stack", ROUTER_LINES, force=force)
    set_marked_block(repo / "CLAUDE.md", "AgentReady Local Stack", ROUTER_LINES, force=force)
    add_unique_line(repo / ".gitignore", ".agent-reports/")
    add_unique_line(repo / ".gitignore", ".agent-state/worktrees/")
    _copy_if_gap(template_root / "forgejo-actions-agent-ci.yml",
                 repo / ".forgejo" / "workflows" / "agent-ci.yml", force)
    _copy_if_gap(template_root / "agent-release-checklist.md", repo / "agent-release-checklist.md", force)

    yaml_path = repo / ".agentready.yaml"
    if force or not yaml_path.exists():
        yaml_path.write_text(AGENTREADY_YAML, encoding="utf-8", newline="")

    (coordination_init_fn or _default_coordination_init)(repo)
    return {"repo": str(repo),
            "files": ["AGENTS.md", "CLAUDE.md", ".gitignore", ".forgejo/workflows/agent-ci.yml",
                      "agent-release-checklist.md", ".agentready.yaml", ".agent-state"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser("agent_bootstrap_repo")
    parser.add_argument("-Repo", "--repo", default=os.getcwd())
    parser.add_argument("-Force", "--force", action="store_true")
    args = parser.parse_args(argv)
    result = bootstrap(Path(args.repo), force=args.force)
    print(f"AgentReady repo bootstrap complete: {result['repo']}")
    print("Added/verified AGENTS.md, CLAUDE.md, .gitignore, .forgejo/workflows/agent-ci.yml, "
          "agent-release-checklist.md, .agentready.yaml, .agent-state")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
