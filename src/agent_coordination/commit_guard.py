"""Commit-guard decision — Python port of `bin/agent-commit-guard.ps1`.

Blocks a commit whose staged paths are not covered by an active, intent-logged claim by the committing
agent. This is the enforcement that makes the Factory's coordination boundaries un-bypassable.

CRITICAL invariants:
- **Fail-closed enforcement**: an internal error or unreadable staged state BLOCKS the commit. An
  explicitly ungoverned repository and a verified empty staged set remain outside the guard.
- **Override** (L58-70): `$env:AGENTREADY_COMMIT_OVERRIDE='<reason>'` allows the commit, loudly + logged
  to a `commit_guard_override` event — visible, never silent.
- **Agent match + non-empty summary** (L79-80): a claim only counts if its summary is non-empty and (when
  the committing agent is declared) it belongs to that agent.
- **Protected-intent** (L83-87): a covering claim on a doctrine/gate/test/manifest path still BLOCKS
  unless the task title/summary names that kind of work.

Until Phase 1F this is shadow-only (PowerShell stays authoritative). `evaluate()` is the verdict;
`main()` is the CLI that `bin/agent-commit-guard.ps1` will forward to after the flip.
"""
from __future__ import annotations

import argparse
import os
import subprocess

from agent_coordination.events import add_event
from agent_coordination.memory_compliance import completion_issues
from agent_coordination.paths import path_overlap, protected_path_intent, to_path_list
from agent_coordination.store import resolve_repo, state_root
from agent_coordination.tasks import get_tasks


def staged_paths(repo) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", str(repo), "diff", "--cached", "--name-only"],
                             capture_output=True, text=True, timeout=15, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"unable to inspect staged paths: {exc}") from exc
    if out.returncode != 0:
        detail = (out.stderr or out.stdout or "git diff failed").strip()
        raise RuntimeError(f"unable to inspect staged paths: {detail}")
    return to_path_list([line for line in out.stdout.splitlines() if line.strip()])


def evaluate(repo=None, paths=None, agent: str | None = None, override: str | None = None) -> dict:
    """The guard verdict. Returns {verdict: allow|block, exit_code, reason, uncovered, protected_failures}."""
    try:
        repo_root = resolve_repo(repo)
        paths = staged_paths(repo_root) if paths is None else to_path_list(paths)
        if not paths:
            return {"verdict": "allow", "exit_code": 0, "reason": "no_paths",
                    "uncovered": [], "protected_failures": [], "memory_failures": []}
        if not (state_root(repo_root) / "tasks").exists():
            return {"verdict": "allow", "exit_code": 0, "reason": "ungoverned",
                    "uncovered": [], "protected_failures": [], "memory_failures": []}
        override = override if override is not None else os.environ.get("AGENTREADY_COMMIT_OVERRIDE")
        if override and override.strip():
            return {"verdict": "allow", "exit_code": 0, "reason": "override",
                    "override": override.strip(), "uncovered": [], "protected_failures": [],
                    "memory_failures": []}

        active = get_tasks(repo_root, status=("claimed", "in_progress"))
        uncovered, protected_failures, memory_failures = [], [], []
        for p in paths:
            covered = False
            protected_issue = ""
            memory_issue = ""
            for task in active:
                if not str(task.get("summary") or "").strip():
                    continue
                if agent and str(task.get("agent")) != agent:
                    continue
                for claimed in to_path_list(task.get("paths")):
                    if path_overlap(claimed, p):
                        issues = protected_path_intent([p], title=str(task.get("title") or ""),
                                                       summary=str(task.get("summary") or ""))
                        if issues:
                            protected_issue = issues[0]
                            continue
                        task_memory_issues = completion_issues(task)
                        if task_memory_issues:
                            memory_issue = f"{task.get('id')}: {' '.join(task_memory_issues)}"
                            memory_failures.append(memory_issue)
                            continue
                        covered = True
                        break
                if covered:
                    break
            if not covered:
                if not memory_issue:
                    (protected_failures if protected_issue else uncovered).append(protected_issue or p)
        memory_failures = list(dict.fromkeys(memory_failures))
        if uncovered or protected_failures or memory_failures:
            return {"verdict": "block", "exit_code": 1, "reason": "blocked",
                    "uncovered": uncovered, "protected_failures": protected_failures,
                    "memory_failures": memory_failures}
        return {"verdict": "allow", "exit_code": 0, "reason": "ok",
                "uncovered": [], "protected_failures": [], "memory_failures": []}
    except Exception as exc:  # noqa: BLE001 - enforcement failures must be visible and blocking
        return {"verdict": "block", "exit_code": 2, "reason": "enforcement_error",
                "error": f"{type(exc).__name__}: {exc}",
                "uncovered": [], "protected_failures": [], "memory_failures": []}


def render_block(
    agent: str | None,
    uncovered: list[str],
    protected_failures: list[str],
    memory_failures: list[str] | None = None,
) -> str:
    who = f" by agent '{agent}'" if agent else ""
    agent_shown = f"'{agent}'" if agent else "<unset>"
    lines = ["", "BLOCKED by the Factory commit-guard."]
    if uncovered:
        lines.append(f"These staged paths have no active, intent-logged claim{who}:")
        lines += [f"    {u}" for u in uncovered]
    if protected_failures:
        lines.append(f"These staged protected paths have a claim, but not an explicit protected-surface intent{who}:")
        lines += [f"    {issue}" for issue in protected_failures]
    if memory_failures:
        lines.append("These covering claims have not satisfied the memory-first receipt gate:")
        lines += [f"    {issue}" for issue in memory_failures]
    lines += [
        "",
        "Already claimed this lane and still blocked? Check, in order:",
        f"  - Agent match: the claim's agent must equal your committing identity ({agent_shown}, from "
        "$env:AGENTREADY_AGENT). A claim under another name is ignored.",
        "  - Task still active: only status claimed/in_progress cover paths -- a handed-off or completed "
        "task does not.",
        "  - Path overlap: a claimed path must equal, or be a parent directory of, the staged path above "
        "(forward slashes; a comma-joined -Paths string is split into separate claims).",
        "  - Logged intent: the claiming task needs a non-empty -Summary.",
        "  - Protected intent: doctrine, gate, test, and manifest paths require the task title/summary to "
        "say that kind of work explicitly.",
        "  - Memory-first: new substantive tasks require graph-query plus Serena-read receipts, or an "
        "explicit no-relevant-memory receipt, before commit.",
        "",
        "Remedy - claim the lane first:",
        f"    agent-task-start -Title '<what>' -Agent <you> -Summary '<intent>' -Paths {','.join(uncovered)}",
        "",
        "Founder override (logged + surfaced):",
        "    $env:AGENTREADY_COMMIT_OVERRIDE='<reason>'  (then commit; the bypass is recorded)",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser("agent_commit_guard")
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--paths", default="")  # comma-joined; empty => read staged
    parser.add_argument("--agent", default=os.environ.get("AGENTREADY_AGENT", ""))
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    agent = args.agent or None
    paths = args.paths if args.paths else None
    override = os.environ.get("AGENTREADY_COMMIT_OVERRIDE")
    repo_root = resolve_repo(args.repo)

    verdict = evaluate(repo_root, paths=paths, agent=agent)
    if verdict["reason"] == "override":
        print("=" * 60)
        print("[commit-guard] OVERRIDE IN EFFECT (logged + surfaced):")
        print(f"    reason: {(override or '').strip()}")
        print(f"    agent : {agent or '<undeclared>'}")
        print("=" * 60)
        try:
            add_event(repo_root, "commit_guard", "commit_guard_override", agent=agent or "",
                      message=(override or "").strip(), data={"paths": paths or staged_paths(repo_root)})
        except Exception as exc:  # noqa: BLE001 - an unlogged override is not an authorized receipt
            print(f"[commit-guard] REFUSED: override could not be durably logged: {type(exc).__name__}: {exc}")
            return 2
        return 0
    if verdict["reason"] == "ungoverned" and not args.quiet:
        print(f"[commit-guard] '{repo_root}' is not coordination-initialized; not gated. "
              "Run agent-coordination-init to govern it.")
        return 0
    if verdict["reason"] == "enforcement_error":
        print(f"[commit-guard] REFUSED: enforcement failed: {verdict.get('error', 'unknown error')}")
        print("Repair the guard/runtime and retry; an unavailable guard never authorizes a commit.")
        return int(verdict["exit_code"])
    if verdict["verdict"] == "block":
        print(render_block(agent, verdict["uncovered"], verdict["protected_failures"],
                           verdict.get("memory_failures")))
        return 1
    if not args.quiet and verdict["reason"] == "ok":
        print("[commit-guard] OK - all staged paths covered by an active intent-logged claim.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
