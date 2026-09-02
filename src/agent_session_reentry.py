# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0
"""Fail-closed, local-first session re-entry receipts for frontier agents.

After a harness update, context reset, or new session, an agent must reconcile
its coordination inbox, one active task, dirty state, and source authority
before mutation. Receipts contain operational identifiers and hashes only; they
never copy source, message bodies, credentials, or repository content.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from agent_runtime_paths import AGENTREADY_HOME, COORDINATION_ROOT, git_common_dir

SCHEMA = "agentready.session_reentry.v1"
FRONTIER_AGENTS = {"claude", "codex"}
ACTIVE_TASK_STATUSES = {"claimed", "in_progress", "started", "active", "wip"}
REQUIRED_ACKS = ("operating_rules", "negative_results", "source_control")
DEFAULT_TTL_MINUTES = 240


def _run(command: list[str], *, cwd: Path | None = None, timeout: int = 30) -> tuple[int, str, str]:
    try:
        result = subprocess.run(
            command,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, "", f"{type(exc).__name__}: {exc}"


def _git(repo: Path, *args: str) -> tuple[int, str, str]:
    return _run(["git", "-C", str(repo), *args])


def _read_json(path: Path, *, attempts: int = 5, delay: float = 0.02) -> object:
    """Read and parse JSON, absorbing a concurrent-writer race.

    A file being rewritten by another process can be momentarily empty, partial,
    or briefly unopenable, which surfaces as ``JSONDecodeError`` or a transient
    ``OSError``. Retry a small, bounded number of times so the race settles. A
    genuinely MISSING file (``FileNotFoundError``) is a real absence, not a race,
    so it is re-raised immediately; a failure that survives every attempt is
    re-raised too, preserving fail-closed behaviour.
    """
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise
        except (json.JSONDecodeError, OSError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(delay)
    raise last_error  # type: ignore[misc]


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _digest(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return "missing"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def repo_identity(repo: str | Path) -> str:
    root = Path(repo).expanduser().resolve(strict=False)
    common = git_common_dir(root)
    identity = common.parent if common and common.name.lower() == ".git" else (common or root)
    return str(identity.resolve(strict=False)).replace("\\", "/").lower()


def nearest_git_repo(path: str | Path) -> Path | None:
    candidate = Path(path).expanduser().resolve(strict=False)
    if candidate.suffix and not candidate.is_dir():
        candidate = candidate.parent
    rc, top, _ = _git(candidate, "rev-parse", "--show-toplevel")
    return Path(top).resolve(strict=False) if rc == 0 and top else None


def receipt_root() -> Path:
    configured = os.environ.get("AGENTREADY_SESSION_REENTRY_DIR", "").strip()
    return Path(configured).expanduser() if configured else AGENTREADY_HOME / "session-reentry"


def _receipt_name(agent: str, session_id: str, repo: str | Path | None = None) -> str:
    key = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    if repo:
        # Scope the receipt to the repository. Without a repo component a receipt
        # issued for one repo would overwrite another repo's receipt at the same
        # (agent, session) filename, and verify would then fail with
        # ``receipt_repo_mismatch`` -- locking the session out of the first repo.
        repo_key = hashlib.sha256(repo_identity(repo).encode("utf-8")).hexdigest()[:12]
        return f"{agent.lower()}-{repo_key}-{key}.json"
    return f"{agent.lower()}-{key}.json"


def receipt_path(agent: str, session_id: str, repo: str | Path | None = None) -> Path:
    return receipt_root() / agent.lower() / _receipt_name(agent, session_id, repo)


def latest_receipt_path(agent: str) -> Path:
    return receipt_root() / agent.lower() / "latest.json"


def harness_snapshot(agent: str, repo: Path) -> dict:
    executable = agent.lower()
    rc, version, error = _run([executable, "--version"], timeout=15)
    optional = [repo / ".agentready.yaml", repo / "AGENTS.md", repo / "CLAUDE.md"]
    for value in os.environ.get("AGENTREADY_HARNESS_FILES", "").split(os.pathsep):
        if value.strip():
            optional.append(Path(value).expanduser())
    snapshot = {
        "agent": agent.lower(),
        "tool_version": version if rc == 0 else f"unavailable:{error or rc}",
        "files": {str(path): _digest(path) for path in [Path(__file__).resolve(), *optional]},
    }
    encoded = json.dumps(snapshot, sort_keys=True, separators=(",", ":")).encode("utf-8")
    snapshot["fingerprint"] = hashlib.sha256(encoded).hexdigest()
    return snapshot


def _trusted_store(store: Path) -> bool:
    for task_path in (store / "tasks").glob("*.json"):
        try:
            task = _read_json(task_path)
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(task, dict):
            repo_root = str(task.get("repo_root") or "").strip()
            if repo_root and Path(repo_root).exists():
                return True
    return False


def unread_urgent_messages(
    agent: str, coordination_root: Path | None = None, session_id: str = ""
) -> list[dict]:
    root = Path(coordination_root or COORDINATION_ROOT)
    if not root.is_dir():
        return [{"id": "coordination-unavailable", "precedence": "IMMEDIATE"}]
    reader_session = str(session_id or "")
    stores = [path for path in root.iterdir() if path.is_dir()]
    if coordination_root is None:
        stores = [path for path in stores if _trusted_store(path)]
    found: dict[str, dict] = {}
    for store in stores:
        for path in (store / "messages").glob("*.json"):
            try:
                message = _read_json(path)
            except (OSError, ValueError, TypeError):
                continue
            if not isinstance(message, dict):
                continue
            recipient = str(message.get("to") or "").lower()
            if recipient not in {agent.lower(), "all"} or bool(message.get("read")):
                continue
            # Session-precise. A message addressed to a specific session (``to_session``)
            # blocks ONLY that session, never a sibling session of the same agent name.
            # An empty ``to_session`` stays name-wide (prior behaviour), and an empty
            # reader ``session_id`` also falls back to name-wide, so nothing regresses;
            # only a proven mismatch is skipped.
            target_session = str(message.get("to_session") or "")
            if target_session and reader_session and target_session != reader_session:
                continue
            # A session must never fence itself: a message the reader itself sent
            # (``from_session``) is excluded so an agent broadcasting an urgent flag
            # does not block its own receipt. Absent field or empty reader = no-op.
            sender_session = str(message.get("from_session") or "")
            if sender_session and reader_session and sender_session == reader_session:
                continue
            precedence = str(message.get("precedence") or "ROUTINE").upper()
            msg_type = str(message.get("type") or "MSG").upper()
            subject = str(message.get("subject") or "")
            blocking = (
                precedence in {"FLASH", "IMMEDIATE"}
                or msg_type == "WARNORD"
                or (precedence == "PRIORITY" and re.search(r"\b(STOP|HOLD)\b", subject, re.I))
            )
            if blocking:
                message_id = str(message.get("id") or path.stem)
                found[message_id] = {
                    "id": message_id,
                    "from": str(message.get("from") or ""),
                    "precedence": precedence,
                    "type": msg_type,
                    "store": store.name,
                }
    return sorted(found.values(), key=lambda row: row["id"])


def all_tasks(coordination_root: Path | None = None) -> list[dict]:
    root = Path(coordination_root or COORDINATION_ROOT)
    tasks: list[dict] = []
    if not root.is_dir():
        return tasks
    for path in root.glob("*/tasks/*.json"):
        try:
            task = _read_json(path)
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(task, dict):
            tasks.append({**task, "_store": path.parent.parent.name})
    return tasks


def find_active_task(agent: str, task_id: str, repo: Path) -> tuple[dict | None, str]:
    matches = [task for task in all_tasks() if str(task.get("id")) == task_id]
    if not matches:
        return None, "task_not_found"
    task = matches[0]
    if str(task.get("agent") or "").lower() != agent.lower():
        return None, "task_owned_by_other_agent"
    if str(task.get("status") or "").lower() not in ACTIVE_TASK_STATUSES:
        return None, f"task_not_active:{task.get('status')}"
    if not task.get("repo_root") or repo_identity(task["repo_root"]) != repo_identity(repo):
        return None, "task_repo_mismatch"
    return task, "ok"


def _local_task_checkout(task: dict | None, repo: Path) -> tuple[Path | None, list[str]]:
    """Return the exact local checkout owned by the task, or fail closed.

    A task may identify the canonical repository while its writes happen in a
    linked worktree.  The worktree must be an absolute, available Git top level
    with the same common-directory identity and recorded branch as ``repo``.
    Tasks created before worktree recording intentionally use ``repo``.
    """
    if task is None:
        return repo, []
    raw = str(task.get("worktree") or "").strip()
    if not raw:
        return repo, []
    requested = Path(raw).expanduser()
    if not requested.is_absolute():
        return None, ["task_worktree_not_absolute"]
    requested = requested.resolve(strict=False)
    if not requested.is_dir():
        return None, ["task_worktree_unavailable"]
    checkout = nearest_git_repo(requested)
    if checkout is None:
        return None, ["task_worktree_not_git_repository"]
    if checkout.resolve(strict=False) != requested:
        return None, ["task_worktree_top_mismatch"]
    if repo_identity(checkout) != repo_identity(repo):
        return None, ["task_worktree_repo_mismatch"]
    expected_branch = str(task.get("branch") or "").strip()
    if expected_branch:
        rc, branch, detail = _git(checkout, "branch", "--show-current")
        if rc != 0:
            return None, [f"task_worktree_branch_unavailable:{detail or 'git_failed'}"]
        if branch != expected_branch:
            return None, ["task_worktree_branch_mismatch"]
    return checkout, []


def dirty_paths(repo: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "status", "--porcelain=v1", "--untracked-files=all"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"git status failed: {type(exc).__name__}: {exc}") from exc
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git status failed")
    paths: list[str] = []
    for line in result.stdout.splitlines():
        value = line[3:] if len(line) > 3 else ""
        if " -> " in value:
            value = value.split(" -> ", 1)[1]
        if value:
            paths.append(value.strip('"'))
    return paths


def _covered(path: str, lanes: Iterable[str]) -> bool:
    changed = path.replace("\\", "/").strip().lower()
    for lane in lanes:
        claimed = str(lane).replace("\\", "/").strip().strip("./").lower()
        if claimed in {"", "."} or changed == claimed or changed.startswith(claimed + "/"):
            return True
    return False


def source_control_status(repo: Path) -> dict:
    rc, head, error = _git(repo, "rev-parse", "HEAD")
    if rc:
        return {"status": "FAIL", "mode": "unavailable", "detail": error}
    authority = os.environ.get("AGENTREADY_AUTHORITY_REMOTE", "").strip()
    if not authority:
        return {"status": "PASS", "mode": "local-only", "local_sha": head}
    rc_branch, branch, _ = _git(repo, "branch", "--show-current")
    if rc_branch or not branch:
        return {"status": "FAIL", "mode": "remote", "detail": "detached_or_unknown_branch"}
    rc_remote, remote, remote_error = _git(repo, "ls-remote", authority, f"refs/heads/{branch}")
    remote_sha = remote.split()[0] if rc_remote == 0 and remote else ""
    return {
        "status": "PASS" if remote_sha == head else "FAIL",
        "mode": "remote",
        "authority": authority,
        "branch": branch,
        "local_sha": head,
        "remote_sha": remote_sha,
        "detail": remote_error,
    }


def evaluate_issue(
    *,
    agent: str,
    repo: Path,
    session_id: str,
    task_id: str,
    acknowledgements: dict[str, bool],
    acknowledge_dirty: bool = False,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
) -> dict:
    agent = agent.lower()
    repo = Path(repo).expanduser().resolve(strict=False)
    failures: list[str] = []
    if agent not in FRONTIER_AGENTS:
        failures.append("unsupported_frontier_agent")
    if not session_id.strip():
        failures.append("missing_session_id")
    for name in REQUIRED_ACKS:
        if not acknowledgements.get(name):
            failures.append(f"missing_ack:{name}")
    urgent = unread_urgent_messages(agent, session_id=session_id)
    failures.extend(f"unread_urgent:{row['id']}" for row in urgent)
    task, task_detail = find_active_task(agent, task_id, repo)
    if task is None:
        failures.append(task_detail)
    checkout, checkout_failures = _local_task_checkout(task, repo)
    failures.extend(checkout_failures)
    dirty: list[str] = []
    if checkout is not None:
        try:
            dirty = dirty_paths(checkout)
        except RuntimeError as exc:
            failures.append(f"dirty_state_unavailable:{exc}")
    uncovered = [path for path in dirty if task is None or not _covered(path, task.get("paths") or [])]
    failures.extend(f"dirty_unclaimed:{path}" for path in uncovered)
    if dirty and not uncovered and not acknowledge_dirty:
        failures.append("dirty_state_requires_ack")
    source = source_control_status(repo)
    if source.get("status") != "PASS":
        failures.append("source_control_not_authoritative")
    now = _utc_now()
    return {
        "schema": SCHEMA,
        "status": "PASS" if not failures else "BLOCKED",
        "agent": agent,
        "session_id": session_id,
        "task_id": task_id,
        "repo_root": str(repo),
        "repo_identity": repo_identity(repo),
        "checkout_root": str(checkout) if checkout is not None else str(task.get("worktree") or "") if task else "",
        "checkout_identity": repo_identity(checkout) if checkout is not None else "",
        "issued_at": _iso(now),
        "expires_at": _iso(now + timedelta(minutes=max(1, ttl_minutes))),
        "acknowledgements": acknowledgements,
        "acknowledged_dirty": bool(acknowledge_dirty and dirty),
        "dirty_paths": dirty,
        "urgent_messages": urgent,
        "source_control": source,
        "harness": harness_snapshot(agent, repo),
        "failures": failures,
    }


def issue_receipt(**kwargs) -> dict:
    receipt = evaluate_issue(**kwargs)
    if receipt["status"] == "PASS":
        path = receipt_path(receipt["agent"], receipt["session_id"], receipt.get("repo_root"))
        _write_json(path, receipt)
        _write_json(latest_receipt_path(receipt["agent"]), receipt)
        receipt["receipt_path"] = str(path)
    return receipt


def _harness_repo_rel(abs_path: str, repo: Path) -> str | None:
    """Repo-relative POSIX path if the harness file is inside ``repo``, else None.

    A harness file outside the repo -- the installed module itself, or a config in
    the home directory -- cannot be claimed as a repo path through ``dirty_paths``
    and so is never forgiven below. That is correct: those are the least
    controllable harness files and should always force re-entry when they change.
    """
    try:
        rel = os.path.relpath(abs_path, repo)
    except ValueError:
        return None
    if rel.startswith(".."):
        return None
    return rel.replace("\\", "/")


def unforgiven_harness_changes(current: dict, receipt: dict, repo: Path) -> list[str]:
    """Harness files whose digest changed since the receipt AND are not forgiven.

    A session that CLAIMED an in-repo harness file (``AGENTS.md``,
    ``.agentready.yaml``, ``CLAUDE.md``) and acknowledged it dirty at issue is
    expected to keep editing it; re-invalidating its own receipt on every such edit
    is a self-churn wedge -- the edit locks the session out, and recovery needs the
    receipt it just lost. So forgive a changed harness file ONLY when it is (a)
    inside the repo and (b) named in the receipt's acknowledged ``dirty_paths``. Any
    other changed harness file -- in-repo but unacked, or out-of-repo -- still forces
    re-entry. An empty return means the fingerprint change is benign (the session's
    own acknowledged edits).
    """
    receipt_files = (receipt.get("harness") or {}).get("files") or {}
    acked = {str(p).replace("\\", "/") for p in (receipt.get("dirty_paths") or [])}
    current_files = current.get("files") or {}
    if not current_files:
        # The fingerprint changed but we cannot enumerate WHICH files, so we cannot
        # prove every change was acknowledged. Fail CLOSED -- never forgive blind.
        return ["<unverifiable-harness-change>"]
    offending: list[str] = []
    for path_str, digest in current_files.items():
        if receipt_files.get(path_str) == digest:
            continue  # unchanged
        rel = _harness_repo_rel(str(path_str), repo)
        if rel is None or rel not in acked:
            offending.append(str(path_str))
    return offending


def verify_receipt(*, agent: str, repo: Path, session_id: str = "", task_ids: Iterable[str] = ()) -> dict:
    path = receipt_path(agent, session_id, repo) if session_id else latest_receipt_path(agent)
    try:
        receipt = _read_json(path)
    except (OSError, ValueError, TypeError) as exc:
        return {"status": "BLOCKED", "failures": [f"receipt_unavailable:{type(exc).__name__}"], "path": str(path)}
    if not isinstance(receipt, dict):
        return {"status": "BLOCKED", "failures": ["receipt_invalid"], "path": str(path)}
    failures: list[str] = []
    if receipt.get("schema") != SCHEMA or receipt.get("status") != "PASS":
        failures.append("receipt_not_pass")
    if str(receipt.get("agent") or "").lower() != agent.lower():
        failures.append("receipt_agent_mismatch")
    if repo_identity(receipt.get("repo_root") or "") != repo_identity(repo):
        failures.append("receipt_repo_mismatch")
    try:
        if datetime.fromisoformat(str(receipt.get("expires_at") or "").replace("Z", "+00:00")) <= _utc_now():
            failures.append("receipt_expired")
    except (TypeError, ValueError):
        failures.append("receipt_expiry_invalid")
    current_harness = harness_snapshot(agent, Path(repo))
    if receipt.get("harness", {}).get("fingerprint") != current_harness.get("fingerprint"):
        # A bare fingerprint mismatch used to hard-fail, which wedged any session
        # that edited a harness file it had claimed and acknowledged dirty. Forgive
        # only those acknowledged in-repo edits; every other harness change (unacked
        # in-repo, or out-of-repo) still forces re-entry.
        if unforgiven_harness_changes(current_harness, receipt, Path(repo)):
            failures.append("harness_changed_since_receipt")
    failures.extend(
        f"unread_urgent:{row['id']}" for row in unread_urgent_messages(agent, session_id=session_id)
    )
    expected = {str(value) for value in task_ids if value}
    receipt_task = str(receipt.get("task_id") or "")
    if expected and receipt_task not in expected:
        failures.append("receipt_task_mismatch")
    task, detail = find_active_task(agent, receipt_task, Path(repo))
    if task is None:
        failures.append(detail)
    else:
        checkout, checkout_failures = _local_task_checkout(task, Path(repo))
        failures.extend(checkout_failures)
        expected_checkout = str(receipt.get("checkout_root") or "")
        if checkout is not None and expected_checkout:
            if checkout.resolve(strict=False) != Path(expected_checkout).resolve(strict=False):
                failures.append("task_worktree_changed_since_receipt")
    return {"status": "PASS" if not failures else "BLOCKED", "failures": list(dict.fromkeys(failures)), "path": str(path)}


def is_bootstrap_command(command: str) -> bool:
    allowed = (
        "agent-coordination coordination-init ",
        "agent-coordination task-status ",
        "agent-coordination task-start ",
        "agent-coordination task-claim ",
        "agent-coordination conflict-check ",
        "agent-coordination memory-compliance ",
        "agent-session-reentry issue ",
        "agent-session-reentry verify ",
        "git status",
        "git diff",
        "git log",
        "git show",
        "git rev-parse",
        "git branch --show-current",
        "git remote -v",
        "git ls-remote",
        "pwd",
        "ls",
    )
    segments = [part.strip().lower() for part in re.split(r"(?:&&|\|\||[;|])", command) if part.strip()]
    return bool(segments) and all(segment.startswith(allowed) for segment in segments)


def hook_response(mode: str, payload: dict, agent: str) -> dict:
    session_id = str(payload.get("session_id") or "")
    tool_input = payload.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path") or payload.get("cwd") or os.getcwd()
    repo = nearest_git_repo(target) or Path(payload.get("cwd") or os.getcwd()).resolve(strict=False)
    verification = verify_receipt(agent=agent, repo=repo, session_id=session_id) if session_id else {
        "status": "BLOCKED", "failures": ["missing_session_id"]
    }
    command = (
        f'agent-session-reentry issue --agent {agent} --repo "{repo}" --session-id "{session_id or "<session-id>"}" '
        "--task-id <task-id> --ack-operating-rules --ack-negative-results --ack-source-control"
    )
    reasons = ", ".join(verification.get("failures") or ["receipt_not_pass"])
    if mode == "session-start":
        status = "PASS" if verification.get("status") == "PASS" else f"REQUIRED ({reasons})"
        return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": f"AgentReady re-entry: {status}. Run: {command}"}}
    tool = str(payload.get("tool_name") or "")
    mutating = tool in {"Write", "Edit", "MultiEdit", "NotebookEdit"}
    if tool in {"Bash", "PowerShell"}:
        mutating = not is_bootstrap_command(str(tool_input.get("command") or ""))
    if any(token in tool.lower() for token in ("write_memory", "edit_memory", "rename_memory", "delete_memory")):
        mutating = True
    if mutating and verification.get("status") != "PASS":
        return {
            "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny"},
            "systemMessage": f"AgentReady re-entry blocked this mutation: {reasons}. Run: {command}",
        }
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow"}}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("issue", "verify"):
        item = sub.add_parser(name)
        item.add_argument("--agent", required=True, choices=sorted(FRONTIER_AGENTS))
        item.add_argument("--repo", required=True)
        item.add_argument("--session-id", required=True)
        if name == "issue":
            item.add_argument("--task-id", required=True)
            item.add_argument("--ack-operating-rules", action="store_true")
            item.add_argument("--ack-negative-results", action="store_true")
            item.add_argument("--ack-source-control", action="store_true")
            item.add_argument("--ack-dirty", action="store_true")
            item.add_argument("--ttl-minutes", type=int, default=DEFAULT_TTL_MINUTES)
    hook = sub.add_parser("hook")
    hook.add_argument("mode", choices=("session-start", "pre-tool-use"))
    hook.add_argument("--agent", required=True, choices=sorted(FRONTIER_AGENTS))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "issue":
        result = issue_receipt(
            agent=args.agent,
            repo=Path(args.repo),
            session_id=args.session_id,
            task_id=args.task_id,
            acknowledgements={
                "operating_rules": args.ack_operating_rules,
                "negative_results": args.ack_negative_results,
                "source_control": args.ack_source_control,
            },
            acknowledge_dirty=args.ack_dirty,
            ttl_minutes=args.ttl_minutes,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    if args.command == "verify":
        result = verify_receipt(agent=args.agent, repo=Path(args.repo), session_id=args.session_id)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["status"] == "PASS" else 1
    try:
        payload = json.load(sys.stdin)
        print(json.dumps(hook_response(args.mode, payload, args.agent)))
        return 0
    except Exception as exc:  # fail closed at the tool boundary
        print(json.dumps({
            "hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny"},
            "systemMessage": f"AgentReady re-entry hook failed closed: {type(exc).__name__}: {exc}",
        }))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
