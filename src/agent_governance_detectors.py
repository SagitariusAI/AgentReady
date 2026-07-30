"""Factory governance detectors -- Python port of `bin/agent-governance-detectors.ps1` (PS->Python Phase 4).

**Advisory, read-only.** Where the commit-guard is PREVENTION (block silent starts), these are DETECTION:
make abandoned / stranded / unpushed / silent work loud. Five detectors, exit 0 when clean / 1 when any
problem is found (a check + a forcing function):

  - stale_claim    : a claimed/in_progress task idle > StaleClaimHours (claimed and forgotten)
  - missing_handoff: a claimed/in_progress task idle > IdleHandoffHours (stopped without handing off)
  - unpushed_batch : commits ahead of upstream, oldest beyond UnpushedAgeHours (not landed/visible)
  - orphan_worktree: a git worktree with no active task behind it
  - silent_commit  : an unpushed commit whose files have no covering claim

Reuses the already-ported coordination engine (`agent_coordination`) for the store reads + path overlap,
exactly as the PowerShell reused `agent-coordination-lib.ps1`. Byte-faithful to the PS finding shapes,
messages (`{n:N0}` -> `{n:,.0f}`), order, and exit code.
"""
from __future__ import annotations

import argparse
import math
import os
import subprocess
from datetime import datetime

from agent_coordination.paths import normalize_path, path_overlap, to_path_list
from agent_coordination.store import resolve_repo
from agent_coordination.tasks import get_tasks

_ACTIVE = ("open", "claimed", "in_progress", "handoff", "review")


def _finding(kind: str, severity: str, message: str) -> dict:
    return {"kind": kind, "severity": severity, "message": message}


def _age_hours(ts: str) -> float:
    if not ts:
        return math.inf
    try:
        return (datetime.now() - datetime.fromisoformat(ts)).total_seconds() / 3600
    except (ValueError, TypeError):
        return math.inf


def _git(repo: str, *args: str) -> str:
    try:
        out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                             timeout=30, check=False)
        return out.stdout
    except Exception:  # noqa: BLE001
        return ""


def claim_detector_findings(repo, stale_hours: int = 24, idle_hours: int = 6) -> list[dict]:
    out = []
    for t in get_tasks(repo, status=("claimed", "in_progress")):
        age = _age_hours(str(t.get("updated_at") or ""))
        if age > stale_hours:
            out.append(_finding("stale_claim", "warn",
                                f"claim '{t.get('id')}' ({t.get('agent')}) idle {age:,.0f}h -- claimed and "
                                "forgotten; close or hand off"))
        elif age > idle_hours:
            out.append(_finding("missing_handoff", "warn",
                                f"agent '{t.get('agent')}' left open claim '{t.get('id')}' idle {age:,.0f}h "
                                "with no handoff -- next worker is blind"))
    return out


def unpushed_findings(repo, max_age_hours: int = 6) -> list[dict]:
    ahead = _git(repo, "rev-list", "--count", "@{upstream}..HEAD").strip()
    try:
        ahead_n = int(ahead)
    except ValueError:
        return []
    if ahead_n <= 0:
        return []
    oldest = ""
    for line in _git(repo, "log", "@{upstream}..HEAD", "--format=%ct").splitlines():
        if line.strip():
            oldest = line.strip()  # keep last -> oldest commit (log is newest-first)
    age_h = 0.0
    if oldest:
        age_h = (datetime.now() - datetime.fromtimestamp(int(oldest))).total_seconds() / 3600
    sev = "warn" if age_h > max_age_hours else "info"
    return [_finding("unpushed_batch", sev,
                     f"{ahead_n} commit(s) ahead of upstream, oldest {age_h:,.0f}h -- not landed or visible "
                     "(DONE = committed + pushed)")]


def orphan_worktree_findings(repo) -> list[dict]:
    paths = [line[len("worktree "):].strip()
             for line in _git(repo, "worktree", "list", "--porcelain").splitlines()
             if line.startswith("worktree ")]
    if len(paths) <= 1:
        return []
    main_root = normalize_path(str(resolve_repo(repo)))
    primary_root = normalize_path(paths[0])
    claimed = [normalize_path(str(t.get("worktree"))) for t in get_tasks(repo, status=_ACTIVE)
               if t.get("worktree")]
    out = []
    for p in paths:
        np = normalize_path(p)
        if np in {main_root, primary_root}:
            continue
        if np not in claimed:
            out.append(_finding("orphan_worktree", "warn",
                                f"worktree '{p}' has no active task behind it -- clean up or claim"))
    return out


def silent_commit_findings(repo, lookback: int = 20) -> list[dict]:
    claim_paths = to_path_list([p for t in get_tasks(repo, status=(*_ACTIVE, "completed"))
                                for p in (t.get("paths") or [])])
    if not _git(repo, "rev-parse", "--abbrev-ref", "@{upstream}").strip():
        return []
    commits = [c for c in _git(repo, "rev-list", "@{upstream}..HEAD").splitlines() if c.strip()][:lookback]
    out = []
    for c in commits:
        files = [f for f in _git(repo, "show", "--name-only", "--format=", c).splitlines() if f.strip()]
        if not files:
            continue
        covered = any(path_overlap(cp, f) for f in files for cp in claim_paths)
        if not covered:
            out.append(_finding("silent_commit", "warn",
                                f"commit {c[:9]} touched {len(files)} file(s) with NO covering claim -- "
                                "silent work"))
    return out


def governance_problems(repo, *, stale_claim_hours: int = 24, idle_handoff_hours: int = 6,
                        unpushed_age_hours: int = 6, silent_commit_lookback: int = 20) -> list[dict]:
    out: list[dict] = []
    out += claim_detector_findings(repo, stale_hours=stale_claim_hours, idle_hours=idle_handoff_hours)
    out += unpushed_findings(repo, max_age_hours=unpushed_age_hours)
    out += orphan_worktree_findings(repo)
    out += silent_commit_findings(repo, lookback=silent_commit_lookback)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser("agent_governance_detectors")
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--stale-claim-hours", type=int, default=24)
    parser.add_argument("--idle-handoff-hours", type=int, default=6)
    parser.add_argument("--unpushed-age-hours", type=int, default=6)
    parser.add_argument("--silent-commit-lookback", type=int, default=20)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    repo = str(resolve_repo(args.repo))
    problems = governance_problems(repo, stale_claim_hours=args.stale_claim_hours,
                                   idle_handoff_hours=args.idle_handoff_hours,
                                   unpushed_age_hours=args.unpushed_age_hours,
                                   silent_commit_lookback=args.silent_commit_lookback)
    if not problems:
        if not args.quiet:
            print("[governance] OK - no governance problems.")
        return 0
    print(f"[governance] {len(problems)} problem(s) in {repo}:")
    for p in problems:
        print(f"  [{p['severity']}] {p['kind']}: {p['message']}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
