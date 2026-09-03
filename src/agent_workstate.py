#!/usr/bin/env python3
# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Project-agnostic work-state gates — the mechanical half of the constitution."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

from agent_runtime_paths import is_agentready_runtime_path

GATE_MARKER_REL = os.path.join(".agentready", "gate_status.json")
HANDOFF_STATUSES = ["complete", "wip", "blocked"]


def _git(repo, *args):
    try:
        out = subprocess.run(["git", "-C", repo, *args],
                             capture_output=True, text=True, timeout=30)
        return out.returncode, out.stdout, out.stderr
    except Exception as exc:  # pragma: no cover - git missing / not a repo
        return 1, "", str(exc)


def head_ref(repo) -> str:
    rc, out, _ = _git(repo, "rev-parse", "HEAD")
    return out.strip() if rc == 0 else ""


def tree_state(repo, paths=None) -> dict:
    """Clean/dirty + the changed paths. Untracked + tracked, ignoring .gitignore.

    ``paths`` scopes the check to those pathspecs (the agent's claimed paths), so
    one lane's uncommitted work — or another agent's in-flight files — does not
    make *your* handoff look dirty. The gate's own marker dir (``.agentready/``)
    is always excluded (ephemeral tooling state, also gitignored)."""
    args = ["status", "--porcelain", "--untracked-files=all"]
    if paths:
        args += ["--", *[str(p) for p in paths if str(p).strip()]]
    rc, out, _ = _git(repo, *args)
    if rc != 0:
        return {"git_ok": False, "clean": True, "count": 0, "files": []}
    files = []
    for ln in out.splitlines():
        if not ln.strip():
            continue
        path = ln[3:] if len(ln) > 3 else ln.strip()
        if is_agentready_runtime_path(path):
            continue
        files.append(path)
    return {"git_ok": True, "clean": not files, "count": len(files), "files": files[:25]}


def write_gate_marker(repo, status, kind) -> dict:
    """A project's gate calls this on pass/fail to record the result against HEAD."""
    path = os.path.join(repo, GATE_MARKER_REL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rec = {
        "status": str(status).lower(),
        "kind": str(kind),
        "ref": head_ref(repo),
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(rec, fh, indent=2)
    return rec


def gate_state(repo) -> dict:
    path = os.path.join(repo, GATE_MARKER_REL)
    if not os.path.isfile(path):
        return {"known": False, "green": False, "fresh": False,
                "detail": "no gate receipt (.agentready/gate_status.json) — gate unverified"}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            rec = json.load(fh)
    except Exception:
        return {"known": False, "green": False, "fresh": False,
                "detail": "unreadable gate receipt"}
    head = head_ref(repo)
    fresh = bool(head) and rec.get("ref") == head
    passed = str(rec.get("status", "")).lower() == "pass"
    detail = f"{rec.get('kind', 'gate')}={rec.get('status', '?')}"
    if not fresh:
        detail += " (STALE — ran against a different commit; re-run the gate)"
    return {"known": True, "green": passed and fresh, "fresh": fresh,
            "passed": passed, "detail": detail, "record": rec}


def evaluate_handoff(repo, status, paths=None) -> dict:
    """Decide whether a handoff of this status may proceed.

    complete -> requires the agent's claimed ``paths`` committed (clean) AND a
                not-known-red/stale gate. With no paths, the whole tree is checked.
    wip/blocked -> always allowed, but stamped INCOMPLETE with the live state.
    """
    status = (status or "complete").lower()
    if status not in HANDOFF_STATUSES:
        status = "complete"
    tree = tree_state(repo, paths)
    gate = gate_state(repo)
    reasons: list[str] = []
    allow = True

    if status == "complete":
        if not tree["clean"]:
            allow = False
            sample = ", ".join(tree["files"][:8])
            more = f" (+{tree['count'] - 8} more)" if tree["count"] > 8 else ""
            reasons.append(f"tree is DIRTY — {tree['count']} uncommitted path(s): {sample}{more}. "
                           "Commit them, or hand off as --status wip.")
        if gate["known"] and not gate["green"]:
            allow = False
            reasons.append(f"gate is NOT green @ HEAD — {gate['detail']}. "
                           "Re-run the project gate (a fresh PASS), or hand off as --status wip.")
        elif not gate["known"]:
            reasons.append(f"NOTE: {gate['detail']} — gate-green could not be verified "
                           "(dirty-tree check still applies).")

    label = {
        "complete": "COMPLETE",
        "wip": "INCOMPLETE (work in progress)",
        "blocked": "INCOMPLETE (blocked)",
    }[status]
    state_line = (f"work state: {'clean' if tree['clean'] else str(tree['count']) + ' uncommitted'}"
                  f" | {gate['detail']}")
    return {"allow": allow, "status": status, "label": label,
            "reasons": reasons, "tree": tree, "gate": gate, "state_line": state_line}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def cmd_tree(a):
    t = tree_state(a.repo)
    if t["clean"]:
        if not getattr(a, "quiet", False):
            print("work tree: clean")
        return 0
    sample = ", ".join(t["files"][:10])
    more = f" (+{t['count'] - 10} more)" if t["count"] > 10 else ""
    print(f"[work-state] {t['count']} UNCOMMITTED path(s) from prior work: {sample}{more}")
    print("   Constitution: commit each gate-green slice before switching tasks "
          "(or `git stash` with a note).")
    return 0


def cmd_handoff_gate(a):
    v = evaluate_handoff(a.repo, a.status, getattr(a, "paths", None))
    if v["allow"]:
        print(f"[handoff-gate] {v['label']} OK -- {v['state_line']}")
        for r in v["reasons"]:
            print(f"   {r}")
        return 0
    print(f"[handoff-gate] REFUSED: a '{v['status']}' handoff over this tree is blocked "
          "(constitution: DONE = gate-green + committed + pushed).")
    for r in v["reasons"]:
        print(f"   - {r}")
    print("   Override (owner-authorized only): re-run with --force-dirty and a reason, "
          "or hand off honestly as --status wip / --status blocked.")
    return 4


def cmd_push_gate(a):
    tree = tree_state(a.repo)
    gate = gate_state(a.repo)
    if tree["clean"] and gate["green"]:
        print(f"[push-gate] OK -- clean tree; {gate['detail']}")
        return 0
    reasons = []
    if not tree["clean"]:
        reasons.append(f"tree has {tree['count']} uncommitted path(s)")
    if not gate["green"]:
        reasons.append(f"gate not green at exact HEAD: {gate['detail']}")
    print(f"[push-gate] REFUSED -- {'; '.join(reasons)}")
    print("   Commit or remove generated dirt, then run the full sweep to a fresh PASS at HEAD.")
    return 5


def cmd_mark(a):
    rec = write_gate_marker(a.repo, a.status, a.kind)
    print(f"[gate-mark] {rec['kind']}={rec['status']} @ {rec['ref'][:12] or 'no-HEAD'}  -> {GATE_MARKER_REL}")
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog="agent_workstate", description="Work-state gates (tree clean? gate green?).")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=os.getcwd())
    sub = p.add_subparsers(dest="command", required=True)

    t = sub.add_parser("tree", parents=[common], help="Report uncommitted work (task-start warning).")
    t.add_argument("--quiet", action="store_true", help="Print nothing when the tree is clean.")
    t.set_defaults(func=cmd_tree)

    h = sub.add_parser("handoff-gate", parents=[common], help="Allow/refuse a handoff by status + tree + gate.")
    h.add_argument("--status", choices=HANDOFF_STATUSES, default="complete")
    h.add_argument("--paths", nargs="*", default=None,
                   help="Claimed paths to scope the dirty check to (default: whole tree).")
    h.set_defaults(func=cmd_handoff_gate)

    pg = sub.add_parser("push-gate", parents=[common], help="Allow/refuse a push (clean + gate green @ HEAD).")
    pg.set_defaults(func=cmd_push_gate)

    m = sub.add_parser("mark", parents=[common], help="Record a gate result (a project's gate calls this).")
    m.add_argument("--status", choices=["pass", "fail"], required=True)
    m.add_argument("--kind", default="gate")
    m.set_defaults(func=cmd_mark)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
