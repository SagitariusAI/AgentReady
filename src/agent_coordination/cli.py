"""Coordination CLI — Python port of the coordination command wrappers (PS->Python migration Phase 1G).

One subcommand per legacy wrapper, preserving its flags, **exit codes**, on-disk artifacts, and human
output:

    task-start        <- bin/agent-task-start.ps1        (exit 3 quality / 2 conflict)
    task-claim        <- bin/agent-task-claim.ps1         (exit 3 quality / 2 claimed-or-conflict)
    task-handoff      <- bin/agent-task-handoff.ps1       (exit 3 quality / 4 work-state refuse)
    task-status       <- bin/agent-task-status.ps1
    task-close        <- bin/agent-task-close.ps1
    task-review       <- bin/agent-task-review.ps1
    conflict-check    <- bin/agent-conflict-check.ps1     (exit 2 conflict)
    worktree-create   <- bin/agent-worktree-create.ps1
    coordination-init <- bin/agent-coordination-init.ps1

The DURABLE coordination logic (task state, events, locks, conflicts, quality gates, handoff/review/
worktree records) is Python. Calls to not-yet-migrated report generators (situational-awareness,
dashboard, release-scorecard, router audit, and data-foundry) stay **best-effort adapter subprocesses**.
The already-Python work-state gate is different: a missing or failed gate refuses a ``complete`` handoff.
A best-effort report failure never changes a durable record or the exit code.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from agent_coordination import events as ev
from agent_coordination import locks as lk
from agent_coordination import memory_compliance as mc
from agent_coordination import paths as pth
from agent_coordination import quality as ql
from agent_coordination import store as st
from agent_coordination import tasks as tk
from agent_coordination.chat import publish_chat, show_unread
from agent_coordination.common import new_task_id, now_stamp
from agent_runtime_paths import worktree_root
from agent_workflow_lanes import WORKFLOW_LANES, classify_workflow_lane

AGENTREADY_HOME = Path(os.environ.get("AGENTREADY_HOME") or Path(__file__).resolve().parents[2])


# ----------------------------------------------------------------------------- adapters (best-effort)
def _venv_python() -> str:
    venv = AGENTREADY_HOME / ".venv" / "Scripts" / "python.exe"
    return str(venv) if venv.exists() else sys.executable


def _pwsh() -> str | None:
    return shutil.which("pwsh") or shutil.which("powershell")


def _best_effort(cmd: list[str], *, cwd: str | None = None, stream: bool = True) -> None:
    """Run an adapter command best-effort. Never raises; failures are swallowed (PS try/catch{})."""
    try:
        out = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=180, check=False)
        if stream and out.stdout:
            print(out.stdout, end="" if out.stdout.endswith("\n") else "\n")
    except Exception:  # noqa: BLE001 - best-effort adapter; never break the coordination action
        return


def _git(repo: Path, *args: str) -> str:
    try:
        out = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                             timeout=30, check=False)
        return out.stdout.rstrip("\n")
    except Exception:  # noqa: BLE001
        return ""


def _default_agent() -> str:
    return os.environ.get("USERNAME", "")


# ----------------------------------------------------------------------------------------- task-start
def cmd_task_start(a: argparse.Namespace) -> int:
    repo = st.resolve_repo(a.repo)
    st.ensure_state(repo)
    banner = show_unread(repo)
    if banner:
        print(banner, end="" if banner.endswith("\n") else "\n")
    # Warn (don't block) on uncommitted work from a prior task.
    ws_mod = AGENTREADY_HOME / "src" / "agent_workstate.py"
    if ws_mod.exists():
        _best_effort([_venv_python(), str(ws_mod), "tree", "--repo", str(repo), "--quiet"])

    paths = pth.to_path_list(a.paths)
    issues = ql.task_start_quality(a.title, summary=a.summary, paths=paths)
    if issues and not a.allow_weak:
        print(ql.quality_failure_message("Task start", issues))
        return 3
    conflicts = pth.path_conflicts(repo, paths)
    if conflicts and not a.force:
        print("Path conflicts detected. Re-run with -Force only after human/agent coordination.")
        _print_conflicts(conflicts)
        return 2

    awareness_report = str(AGENTREADY_HOME / "reports" / "situational-awareness" / "latest.md")
    dashboard_report = str(AGENTREADY_HOME / "reports" / "agent-dashboard" / "latest.md")
    if not a.skip_awareness:
        sa = AGENTREADY_HOME / "bin" / "agent-situational-awareness.ps1"
        dash = AGENTREADY_HOME / "bin" / "agent-agent-dashboard.ps1"
        psh = _pwsh()
        if psh and sa.exists():
            _best_effort([psh, "-NoProfile", "-File", str(sa), "-Task", a.title,
                          "-Agent", a.agent, "-Repo", str(repo)])
        if psh and dash.exists():
            _best_effort([psh, "-NoProfile", "-File", str(dash), "-Repo", str(repo),
                          "-SkipAwarenessRefresh"])

    task_id = new_task_id(a.title)
    stamp = now_stamp()
    lane, lane_source = classify_workflow_lane({
        "workflow_lane": a.workflow_lane,
        "workflow_lane_source": "explicit" if a.workflow_lane else "",
        "title": a.title,
        "summary": a.summary,
    })
    task = {
        "id": task_id, "repo_root": str(repo), "title": a.title, "status": "claimed",
        "agent": a.agent, "summary": a.summary, "intent_summary": a.summary,
        "workflow_lane": lane, "workflow_lane_source": lane_source,
        "paths": paths, "branch": "", "worktree": "",
        "created_at": stamp, "updated_at": stamp,
        "evidence": [awareness_report, dashboard_report], "blockers": [], "next_actions": [],
        "quality_override": {"allowed": bool(a.allow_weak), "issues": issues if a.allow_weak else []},
        "memory_compliance": mc.new_policy(required=True, substantive=True),
    }
    tk.write_task(repo, task)
    lk.set_locks(repo, task)
    ev.add_event(repo, task_id, "task_started", agent=a.agent, message=a.title,
                 data={"paths": paths, "summary": a.summary, "workflow_lane": lane})

    chat_paths = f" [paths: {', '.join(paths)}]" if paths else ""
    publish_chat(a.agent, f"started task: {a.title}{chat_paths}")

    if a.create_worktree:
        _worktree_create(repo, task_id, a.agent, base="HEAD", force=False)

    print(f"Agent task started: {task_id}")
    print(str(tk.task_path(repo, task_id)))
    return 0


# ----------------------------------------------------------------------------------------- task-claim
def cmd_task_claim(a: argparse.Namespace) -> int:
    repo = st.resolve_repo(a.repo)
    task = tk.read_task(repo, a.task_id)
    claim_paths = pth.to_path_list(a.paths)
    if not claim_paths:
        claim_paths = pth.to_path_list(task.get("paths"))

    issues = ql.claim_quality(claim_paths)
    if issues and not a.allow_weak:
        print(ql.quality_failure_message("Task claim", issues))
        return 3
    if task.get("agent") and task.get("agent") != a.agent and not a.force:
        print(f"Task is already claimed by {task.get('agent')}. Use -Force only after coordination.")
        return 2
    conflicts = pth.path_conflicts(repo, claim_paths, exclude_task_id=a.task_id)
    if conflicts and not a.force:
        print("Path conflicts detected. Re-run with -Force only after coordination.")
        _print_conflicts(conflicts)
        return 2

    task["agent"] = a.agent
    task["status"] = "claimed"
    task["paths"] = claim_paths
    tk.write_task(repo, task)
    lk.set_locks(repo, task)
    ev.add_event(repo, a.task_id, "task_claimed", agent=a.agent, message=f"Claimed by {a.agent}",
                 data={"paths": claim_paths})
    print(f"Agent task claimed: {a.task_id} by {a.agent}")
    return 0


# --------------------------------------------------------------------------------------- task-handoff
def _report_pointer(label: str, path: str) -> str:
    p = Path(path)
    if p.exists():
        mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%dT%H:%M:%S")
        return (f"- {label}: {path} (last_write={mtime}; pointer only, verify freshness and commit "
                f"coverage before using as evidence)")
    return f"- {label}: {path} (missing; pointer only)"


_STATUS_LABELS = {"complete": "COMPLETE", "wip": "INCOMPLETE (work in progress)",
                  "blocked": "INCOMPLETE (blocked)"}


def cmd_task_handoff(a: argparse.Namespace) -> int:
    repo = st.resolve_repo(a.repo)
    task = tk.read_task(repo, a.task_id)
    state = st.ensure_state(repo)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    handoff_path = state / "handoffs" / f"{stamp}-{a.task_id}.md"
    operator = a.operator or _default_agent()
    work_author = a.agent or task.get("agent") or operator or _default_agent()
    evidence_text = (a.evidence or a.test_summary or a.tests or str(task.get("test_summary") or "")
                     or "")

    issues = ql.handoff_quality(task, summary=a.summary, evidence=evidence_text, next_action=a.next)
    if issues and not a.allow_weak:
        print(ql.quality_failure_message("Task handoff", issues))
        return 3
    if a.status == "complete":
        memory_issues = mc.completion_issues(task)
        if memory_issues:
            print("Memory compliance gate failed:")
            for issue in memory_issues:
                print(f"- {issue}")
            print("Record the task's graph query and Serena read receipts with agent-task-memory, "
                  "or add an explicit no-relevant-memory receipt with query evidence.")
            return 5

    # Work-state gate (constitution Article VI): a 'complete' handoff may not happen over a dirty or
    # gate-red/stale tree. The gate logic is already Python (agent_workstate.py); call it as a shim.
    force_note = ""
    ws_mod = AGENTREADY_HOME / "src" / "agent_workstate.py"
    ws_code = 0
    if ws_mod.exists():
        ws_args = [_venv_python(), str(ws_mod), "handoff-gate", "--repo", str(repo), "--status", a.status]
        ws_paths = [p for p in (task.get("paths") or []) if p]
        if ws_paths:
            ws_args += ["--paths", *ws_paths]
        try:
            res = subprocess.run(ws_args, capture_output=True, text=True, timeout=180, check=False)
            if res.stdout:
                print(res.stdout, end="" if res.stdout.endswith("\n") else "\n")
            ws_code = res.returncode
        except Exception as exc:  # noqa: BLE001 - unavailable enforcement refuses terminal completion
            ws_code = 4
            print(f"[handoff-gate] REFUSED: work-state gate failed: {type(exc).__name__}: {exc}")
    elif a.status == "complete":
        ws_code = 4
        print(f"[handoff-gate] REFUSED: work-state gate is missing: {ws_mod}")
    if ws_code != 0:
        if not a.force_dirty:
            print("")
            print(f"Handoff REFUSED. A '{a.status}' handoff requires a clean, gate-green tree.")
            print("Hand off honestly as -Status wip / -Status blocked, or (founder-authorized) "
                  "-ForceDirty -DirtyReason '<why>'.")
            return 4
        if not a.dirty_reason:
            print('-ForceDirty requires -DirtyReason "<founder-authorized reason>".')
            return 4
        force_note = f" (FORCED over non-clean/green tree: {a.dirty_reason})"
        print(f"[work-state] OVERRIDE accepted -- {a.dirty_reason}")

    status_label = _STATUS_LABELS.get(a.status, a.status)
    git_head = _git(repo, "log", "-1", "--oneline")
    git_status = _git(repo, "status", "--short")
    scorecard = str(repo / ".agent-reports" / "release-scorecard" / "latest.md")
    ci_log = str(repo / ".agent-reports" / "ci" / "agent-ci-local-latest.log")
    extra_reports = [r for r in (a.report_path or []) if r]

    summary_text = a.summary or str(task.get("summary") or "")
    memory_summary = mc.compliance_summary(task)
    lines = [
        f"# Agent Handoff: {a.task_id}", "",
        f"- Task: {task.get('title')}",
        f"- Agent: {work_author}",
        f"- Operator: {operator}",
        f"- Status: {status_label}{force_note}",
        f"- Branch: {task.get('branch')}",
        f"- Worktree: {task.get('worktree')}",
        f"- Generated: {now_stamp()}",
        f"- Git head: {git_head}", "",
        "## Summary", "", summary_text, "",
        "## Claimed Paths", "",
    ]
    lines += [f"- {p}" for p in (task.get("paths") or [])]
    lines += [
        "", "## Memory Compliance", "",
        f"- Status: `{memory_summary['status']}`",
        f"- Receipts: `{memory_summary['receipt_count']}`",
        f"- Kinds: `{', '.join(memory_summary['receipt_kinds']) or 'none'}`",
    ]
    lines += [f"- Issue: {issue}" for issue in memory_summary["issues"]]
    lines += [
        "", "## Tests / Evidence", "",
        evidence_text or ("No explicit test/evidence summary provided. Treat report paths below as "
                          "pointers only; verify freshness, commit coverage, and PASS/WARN/FAIL status "
                          "before using them as evidence."),
        "", "## Report Pointers", "",
        "These paths are convenience pointers, not proof by themselves. Handoffs must interpret whether "
        "each report is current, stale, skipped, failing, or not applicable.", "",
        _report_pointer("CI latest", ci_log),
        _report_pointer("Release scorecard", scorecard),
    ]
    lines += [_report_pointer("Agent receipt", r) for r in extra_reports]
    lines += [
        "", "## Blockers", "", (a.blockers or "None recorded."),
        "", "## Next Actions", "", (a.next or "No next actions recorded."),
        "", "## Git Status", "", "```text",
    ]
    lines += git_status.splitlines() if git_status else []
    lines += ["```"]
    handoff_path.parent.mkdir(parents=True, exist_ok=True)
    handoff_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    is_complete = a.status == "complete"
    task["status"] = "completed" if is_complete else "handoff"
    task["summary"] = a.summary or task.get("summary")
    task["agent"] = work_author
    task["operator"] = operator
    if is_complete:
        task["resolution"] = "completed"
        task["completed_at"] = now_stamp()
    if evidence_text:
        task["test_summary"] = evidence_text
    task["evidence"] = list(task.get("evidence") or []) + [str(handoff_path)]
    for report in extra_reports:
        if report not in task["evidence"]:
            task["evidence"] = list(task["evidence"]) + [report]
    if a.blockers:
        task["blockers"] = list(task.get("blockers") or []) + [a.blockers]
    if a.next:
        task["next_actions"] = list(task.get("next_actions") or []) + [a.next]
    tk.write_task(repo, task)
    if is_complete:
        lk.remove_locks(repo, a.task_id)  # terminal handoff frees the lane
    else:
        lk.set_locks(repo, task)          # still-open lane stays protected

    ev.add_event(repo, a.task_id, "handoff", agent=work_author, message=a.summary,
                 data={"handoff": str(handoff_path), "status": a.status, "blockers": a.blockers,
                       "next": a.next, "operator": operator, "work_author": work_author,
                       "test_summary": evidence_text, "report_paths": extra_reports,
                       "memory_compliance": memory_summary})

    chat_next = f" - next: {a.next}" if a.next else ""
    publish_chat(work_author, f"handed off [{a.status}]: {task.get('title')}{chat_next}")

    # Terminal handoffs are the right boundary for Factory data capture. Best-effort, never blocks.
    runner = AGENTREADY_HOME / "bin" / "agent-data-foundry-event-runner.ps1"
    psh = _pwsh()
    if psh and runner.exists():
        _best_effort([psh, "-NoProfile", "-File", str(runner), "-EventType", "handoff",
                      "-TaskId", a.task_id, "-SourceRepo", str(repo), "-DebounceSeconds", "300",
                      "-MaxRoots", "1000", "-LimitPerRoot", "10000"])

    print(f"Agent handoff written: {handoff_path}")
    return 0


# ---------------------------------------------------------------------------------------- task-status
def cmd_task_status(a: argparse.Namespace) -> int:
    repo = st.resolve_repo(a.repo)
    st.ensure_state(repo)
    banner = show_unread(repo)
    if banner:
        print(banner, end="" if banner.endswith("\n") else "\n")

    if a.task_id:
        task = tk.read_task(repo, a.task_id)
        print(json.dumps(task, indent=2, ensure_ascii=True))
        events = st.state_dir(repo, "events") / f"{a.task_id}.jsonl"
        if events.exists():
            print("")
            print(f"Events: {events}")
            tail = events.read_text(encoding="utf-8").splitlines()[-20:]
            for line in tail:
                print(line)
        return 0

    statuses = () if a.all else ("open", "claimed", "in_progress", "handoff", "review")
    rows = tk.get_tasks(repo, status=statuses)
    if not rows:
        print("No AgentReady tasks recorded." if a.all else "No active AgentReady tasks.")
        return 0
    rows.sort(key=lambda t: t.get("updated_at") or "", reverse=True)
    _print_task_table(rows)
    return 0


# ----------------------------------------------------------------------------------------- task-close
def cmd_task_close(a: argparse.Namespace) -> int:
    repo = st.resolve_repo(a.repo)
    task = tk.read_task(repo, a.task_id)
    task["status"] = "closed"
    task["resolution"] = a.resolution
    if a.summary:
        task["summary"] = a.summary
    task["closed_at"] = now_stamp()
    tk.write_task(repo, task)
    if not a.keep_locks:
        lk.remove_locks(repo, a.task_id)
    if a.remove_worktree and task.get("worktree"):
        _remove_worktree(repo, task)
    ev.add_event(repo, a.task_id, "task_closed", agent=a.agent, message=a.resolution,
                 data={"summary": a.summary})
    print(f"Agent task closed: {a.task_id} ({a.resolution})")
    return 0


def _remove_worktree(repo: Path, task: dict) -> None:
    worktree = task.get("worktree")
    if not isinstance(worktree, str) or not worktree:
        return
    repo_root = task.get("repo_root")
    remove_root = Path(repo_root) if repo_root and Path(repo_root).exists() else repo
    _git(remove_root, "worktree", "remove", "--force", str(worktree))
    _git(remove_root, "worktree", "prune")
    wt = Path(worktree)
    if wt.exists():
        try:
            resolved = wt.resolve()
            root = worktree_root(repo).resolve()
            if str(resolved).lower().startswith(str(root).lower()):
                shutil.rmtree(resolved, ignore_errors=True)
            else:
                print(f"Refusing to force-remove worktree outside AgentReady root: {resolved}")
        except (OSError, RuntimeError) as exc:
            print(f"Unable to remove residual worktree directory {wt}: {exc}", file=sys.stderr)
    branch = task.get("branch")
    if branch and str(branch).startswith("agent/"):
        _git(remove_root, "branch", "-D", str(branch))


# ---------------------------------------------------------------------------------------- task-review
def cmd_task_review(a: argparse.Namespace) -> int:
    repo = st.resolve_repo(a.repo)
    state = st.ensure_state(repo)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    review_path = state / "reviews" / f"{stamp}-review.md"

    if a.run_scorecard:
        sc = AGENTREADY_HOME / "bin" / "agent-release-scorecard.ps1"
        psh = _pwsh()
        if psh and sc.exists():
            _best_effort([psh, "-NoProfile", "-File", str(sc), "-Repo", str(repo), "-WarnOnly"])

    head = _git(repo, "log", "-1", "--oneline")
    status = _git(repo, "status", "--short")
    scorecard = str(repo / ".agent-reports" / "release-scorecard" / "latest.md")
    ci = str(repo / ".agent-reports" / "ci" / "agent-ci-local-latest.log")

    router_audit = ""
    router = AGENTREADY_HOME / "bin" / "agent-tool-router.ps1"
    psh = _pwsh()
    if psh and router.exists():
        try:
            res = subprocess.run([psh, "-NoProfile", "-File", str(router), "-Profile", "release",
                                  "-Mode", "Audit"], cwd=str(repo), capture_output=True, text=True,
                                 timeout=180, check=False)
            router_audit = res.stdout.rstrip("\n")
        except Exception:  # noqa: BLE001
            router_audit = "(router audit unavailable)"

    lines = [
        "# Agent Review Record", "",
        f"- Generated: {now_stamp()}",
        f"- Agent: {a.agent}",
        f"- Task: {a.task_id}",
        f"- Git head: {head}",
        f"- Scorecard: {scorecard}",
        f"- CI: {ci}", "",
        "## Router Audit", "", "```text", router_audit, "```", "",
        "## Git Status", "", "```text",
    ]
    lines += status.splitlines() if status else []
    lines += ["```"]
    review_path.parent.mkdir(parents=True, exist_ok=True)
    review_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    if a.task_id:
        task = tk.read_task(repo, a.task_id)
        task["status"] = "review"
        task["evidence"] = list(task.get("evidence") or []) + [str(review_path)]
        tk.write_task(repo, task)
        ev.add_event(repo, a.task_id, "review_recorded", agent=a.agent, message=str(review_path),
                     data={"review": str(review_path)})
    print(f"Agent review written: {review_path}")
    return 0


# ------------------------------------------------------------------------------------- conflict-check
def cmd_conflict_check(a: argparse.Namespace) -> int:
    repo = st.resolve_repo(a.repo)
    st.ensure_state(repo)
    banner = show_unread(repo)
    if banner:
        print(banner, end="" if banner.endswith("\n") else "\n")

    paths = pth.to_path_list(a.paths)
    if not paths and a.task_id:
        task = tk.read_task(repo, a.task_id)
        paths = pth.to_path_list(task.get("paths"))
    conflicts = pth.path_conflicts(repo, paths, exclude_task_id=a.task_id)
    if conflicts:
        print("Agent path conflicts:")
        _print_conflicts(conflicts)
        return 2
    print("No AgentReady path conflicts detected.")
    return 0


# ------------------------------------------------------------------------------------ worktree-create
def _worktree_create(repo: Path, task_id: str, agent: str, base: str, force: bool) -> None:
    task = tk.read_task(repo, task_id)
    wt_path = st.worktree_path(repo, task_id)
    branch = f"agent/{re.sub(r'[^A-Za-z0-9_-]', '-', agent)}/{task_id}"

    if wt_path.exists() and not force:
        print(f"Worktree already exists: {wt_path}")
    else:
        wt_path.parent.mkdir(parents=True, exist_ok=True)
        added = subprocess.run(["git", "-C", str(repo), "worktree", "add", "-b", branch,
                                str(wt_path), base], capture_output=True, text=True, check=False)
        if added.stdout:
            print(added.stdout, end="" if added.stdout.endswith("\n") else "\n")
        if added.returncode != 0:
            subprocess.run(["git", "-C", str(repo), "worktree", "add", str(wt_path), branch],
                           capture_output=True, text=True, check=False)

    task["branch"] = branch
    task["worktree"] = str(wt_path)
    task["status"] = "in_progress"
    tk.write_task(repo, task)
    lk.set_locks(repo, task)

    state = st.ensure_state(repo)
    pointer = {"task_id": task_id, "branch": branch, "worktree": str(wt_path), "agent": agent,
               "created_at": now_stamp()}
    (state / "worktrees" / f"{task_id}.json").write_text(
        json.dumps(pointer, indent=2, ensure_ascii=True), encoding="utf-8")
    ev.add_event(repo, task_id, "worktree_created", agent=agent, message=str(wt_path),
                 data={"branch": branch, "worktree": str(wt_path)})
    print(f"Agent worktree ready: {wt_path}")
    print(f"Branch: {branch}")


def cmd_worktree_create(a: argparse.Namespace) -> int:
    repo = st.resolve_repo(a.repo)
    _worktree_create(repo, a.task_id, a.agent, base=a.base, force=a.force)
    return 0


# --------------------------------------------------------------------------------- coordination-init
def cmd_coordination_init(a: argparse.Namespace) -> int:
    state = st.ensure_state(st.resolve_repo(a.repo))
    print(f"Agent coordination state ready: {state}")
    return 0


# ------------------------------------------------------------------------------ memory compliance
def cmd_task_memory(a: argparse.Namespace) -> int:
    repo = st.resolve_repo(a.repo)
    task = tk.read_task(repo, a.task_id)
    receipt = mc.build_receipt(
        a.task_id,
        kind=a.kind,
        agent=a.agent,
        store=a.store,
        query=a.query,
        memory_name=a.memory_name,
        evidence=a.evidence,
        reason=a.reason,
    )
    summary = mc.append_receipt(task, receipt)
    tk.write_task(repo, task)
    ev.add_event(repo, a.task_id, "memory_receipt", agent=a.agent, message=a.kind,
                 data={"receipt": receipt, "compliance": summary})
    print(f"Memory receipt recorded: {receipt['receipt_id']} ({a.kind})")
    print(f"Memory compliance: {summary['status']}")
    return 0


def cmd_memory_compliance(a: argparse.Namespace) -> int:
    repo = st.resolve_repo(a.repo)
    report = mc.audit_tasks(tk.get_tasks(repo, status=()), stale_hours=a.stale_hours)
    path = mc.write_audit_report(repo, report, record_remediation=a.record_remediation)
    counts = report["counts"]
    print(f"Memory compliance report: {path}")
    print(json.dumps(counts, sort_keys=True))
    if report["findings"]:
        print(f"Findings: {len(report['findings'])}")
    return 1 if a.fail_on_missing and counts.get("missing", 0) else 0


# ----------------------------------------------------------------------------------------- rendering
def _print_conflicts(conflicts: list[dict]) -> None:
    cols = ["task_id", "status", "agent", "existing_path", "requested_path", "title"]
    _table(cols, [[str(c.get(k, "")) for k in cols] for c in conflicts])


def _print_task_table(rows: list[dict]) -> None:
    cols = ["id", "status", "memory", "agent", "title", "updated_at", "branch", "worktree"]
    table_rows = []
    for row in rows:
        values = dict(row)
        values["memory"] = mc.compliance_summary(row)["status"]
        table_rows.append([str(values.get(k, "")) for k in cols])
    _table(cols, table_rows)


def _table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    print("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


# ----------------------------------------------------------------------------------------------- main
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser("agent_coordination.cli")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("task-start")
    s.add_argument("--repo", default=os.getcwd())
    s.add_argument("--title", required=True)
    s.add_argument("--agent", default=_default_agent())
    s.add_argument("--summary", default="")
    s.add_argument("--workflow-lane", choices=WORKFLOW_LANES, default="")
    s.add_argument("--paths", default="")
    s.add_argument("--create-worktree", action="store_true")
    s.add_argument("--skip-awareness", action="store_true")
    s.add_argument("--allow-weak", action="store_true")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_task_start)

    s = sub.add_parser("task-claim")
    s.add_argument("--repo", default=os.getcwd())
    s.add_argument("--task-id", required=True)
    s.add_argument("--agent", default=_default_agent())
    s.add_argument("--paths", default="")
    s.add_argument("--allow-weak", action="store_true")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_task_claim)

    s = sub.add_parser("task-handoff")
    s.add_argument("--repo", default=os.getcwd())
    s.add_argument("--task-id", required=True)
    s.add_argument("--agent", default="")
    s.add_argument("--operator", default=_default_agent())
    s.add_argument("--summary", default="")
    s.add_argument("--next", default="")
    s.add_argument("--blockers", default="")
    s.add_argument("--tests", default="")
    s.add_argument("--evidence", default="")
    s.add_argument("--test-summary", default="")
    s.add_argument("--report-path", action="append", default=[])
    s.add_argument("--allow-weak", action="store_true")
    s.add_argument("--status", choices=("complete", "wip", "blocked"), default="complete")
    s.add_argument("--force-dirty", action="store_true")
    s.add_argument("--dirty-reason", default="")
    s.set_defaults(func=cmd_task_handoff)

    s = sub.add_parser("task-status")
    s.add_argument("--repo", default=os.getcwd())
    s.add_argument("--task-id", default="")
    s.add_argument("--all", action="store_true")
    s.set_defaults(func=cmd_task_status)

    s = sub.add_parser("task-close")
    s.add_argument("--repo", default=os.getcwd())
    s.add_argument("--task-id", required=True)
    s.add_argument("--agent", default=_default_agent())
    s.add_argument("--resolution", default="completed")
    s.add_argument("--summary", default="")
    s.add_argument("--keep-locks", action="store_true")
    s.add_argument("--remove-worktree", action="store_true")
    s.set_defaults(func=cmd_task_close)

    s = sub.add_parser("task-review")
    s.add_argument("--repo", default=os.getcwd())
    s.add_argument("--task-id", default="")
    s.add_argument("--agent", default=_default_agent())
    s.add_argument("--run-scorecard", action="store_true")
    s.set_defaults(func=cmd_task_review)

    s = sub.add_parser("conflict-check")
    s.add_argument("--repo", default=os.getcwd())
    s.add_argument("--paths", default="")
    s.add_argument("--task-id", default="")
    s.set_defaults(func=cmd_conflict_check)

    s = sub.add_parser("worktree-create")
    s.add_argument("--repo", default=os.getcwd())
    s.add_argument("--task-id", required=True)
    s.add_argument("--agent", default=_default_agent())
    s.add_argument("--base", default="HEAD")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_worktree_create)

    s = sub.add_parser("coordination-init")
    s.add_argument("--repo", default=os.getcwd())
    s.set_defaults(func=cmd_coordination_init)

    s = sub.add_parser("task-memory")
    s.add_argument("--repo", default=os.getcwd())
    s.add_argument("--task-id", required=True)
    s.add_argument("--agent", default=_default_agent())
    s.add_argument("--kind", required=True, choices=mc.RECEIPT_KINDS)
    s.add_argument("--store", default="")
    s.add_argument("--query", default="")
    s.add_argument("--memory-name", default="")
    s.add_argument("--evidence", required=True)
    s.add_argument("--reason", default="")
    s.set_defaults(func=cmd_task_memory)

    s = sub.add_parser("memory-compliance")
    s.add_argument("--repo", default=os.getcwd())
    s.add_argument("--stale-hours", type=int, default=72)
    s.add_argument("--record-remediation", action="store_true")
    s.add_argument("--fail-on-missing", action="store_true")
    s.set_defaults(func=cmd_memory_compliance)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except NotADirectoryError as exc:
        # Clear, non-traceback error for the file-as-repo-root misparse
        # (FACTORY-ANOMALY-20260620-claim-helper-path-misparse).
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
