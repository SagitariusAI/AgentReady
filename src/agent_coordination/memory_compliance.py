"""Structured memory-use receipts and append-only compliance reporting.

New substantive tasks are memory-audited by default.  Completion requires proof that the
agent queried the memory graph and then either read a relevant Serena memory or explicitly
recorded why the query found no relevant memory.  Durable memory writes and graph refreshes
are also recorded, but are required only when a write occurred.

Legacy task records are never silently rewritten.  The audit command reports them as
``legacy_untracked`` and can append remediation events without changing historical fields.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from agent_coordination.common import now_stamp, write_json
from agent_coordination.events import add_event
from agent_coordination.quality import task_start_quality
from agent_coordination.store import ensure_state

SCHEMA_VERSION = "agentready.memory_compliance.v1"
RECEIPT_KINDS = (
    "graph_query",
    "serena_read",
    "durable_write",
    "graph_refresh",
    "no_relevant_memory",
)
READ_KINDS = {"serena_read", "no_relevant_memory"}


def new_policy(*, required: bool = True, substantive: bool = True) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "required": bool(required),
        "substantive": bool(substantive),
        "receipts": [],
    }


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _receipt_id(task_id: str, kind: str, stamp: str, fields: dict[str, Any]) -> str:
    body = json.dumps([task_id, kind, stamp, fields], sort_keys=True, ensure_ascii=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:20]


def build_receipt(
    task_id: str,
    *,
    kind: str,
    agent: str,
    store: str = "",
    query: str = "",
    memory_name: str = "",
    evidence: str = "",
    reason: str = "",
    timestamp: str = "",
) -> dict[str, Any]:
    if kind not in RECEIPT_KINDS:
        raise ValueError(f"Unsupported memory receipt kind: {kind}")
    fields = {
        "agent": _clean(agent),
        "store": _clean(store),
        "query": _clean(query),
        "memory_name": _clean(memory_name),
        "evidence": _clean(evidence),
        "reason": _clean(reason),
    }
    if not fields["agent"]:
        raise ValueError("Memory receipt requires an agent.")
    if not fields["evidence"]:
        raise ValueError("Memory receipt requires an evidence pointer or interpreted result.")
    if kind in {"graph_query", "no_relevant_memory"} and not fields["query"]:
        raise ValueError(f"{kind} receipt requires the query that was executed.")
    if kind in {"serena_read", "durable_write"}:
        if not fields["store"]:
            raise ValueError(f"{kind} receipt requires the Serena store.")
        if not fields["memory_name"]:
            raise ValueError(f"{kind} receipt requires the memory name.")
    if kind == "no_relevant_memory" and not fields["reason"]:
        raise ValueError("no_relevant_memory receipt requires an explicit reason.")
    stamp = _clean(timestamp) or now_stamp()
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "receipt_id": _receipt_id(task_id, kind, stamp, fields),
        "kind": kind,
        "timestamp": stamp,
        **fields,
    }
    return receipt


def append_receipt(task: dict[str, Any], receipt: dict[str, Any]) -> dict[str, Any]:
    policy = task.get("memory_compliance")
    if not isinstance(policy, dict):
        policy = new_policy()
    receipts = list(policy.get("receipts") or [])
    if not any(row.get("receipt_id") == receipt.get("receipt_id") for row in receipts):
        receipts.append(dict(receipt))
    policy = {**policy, "schema_version": SCHEMA_VERSION, "receipts": receipts}
    task["memory_compliance"] = policy
    return compliance_summary(task)


def compliance_summary(task: dict[str, Any]) -> dict[str, Any]:
    policy = task.get("memory_compliance")
    if not isinstance(policy, dict):
        return {
            "schema_version": SCHEMA_VERSION,
            "required": False,
            "substantive": True,
            "status": "legacy_untracked",
            "receipt_count": 0,
            "receipt_kinds": [],
            "issues": ["Task predates structured memory compliance receipts."],
        }
    required = bool(policy.get("required", True))
    substantive = bool(policy.get("substantive", True))
    receipts = [r for r in (policy.get("receipts") or []) if isinstance(r, dict)]
    kinds = [str(r.get("kind") or "") for r in receipts]
    issues: list[str] = []
    if required and substantive:
        if "graph_query" not in kinds:
            issues.append("Missing memory graph query receipt.")
        if not any(kind in READ_KINDS for kind in kinds):
            issues.append("Missing Serena read or explicit no-relevant-memory receipt.")
        if "durable_write" in kinds and "graph_refresh" not in kinds:
            issues.append("Durable memory write has no graph refresh receipt.")
    status = "not_required"
    if required and substantive:
        status = "compliant" if not issues else "missing"
    return {
        "schema_version": SCHEMA_VERSION,
        "required": required,
        "substantive": substantive,
        "status": status,
        "receipt_count": len(receipts),
        "receipt_kinds": kinds,
        "issues": issues,
    }


def completion_issues(task: dict[str, Any]) -> list[str]:
    summary = compliance_summary(task)
    return list(summary["issues"]) if summary["status"] == "missing" else []


def _parse_stamp(value: Any) -> datetime | None:
    text = _clean(value)
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def audit_tasks(tasks: list[dict[str, Any]], *, stale_hours: int = 72, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    stale_before = now - timedelta(hours=max(1, stale_hours))
    findings: list[dict[str, Any]] = []
    counts = {
        "tasks_seen": len(tasks),
        "compliant": 0,
        "missing": 0,
        "legacy_untracked": 0,
        "not_required": 0,
        "stale_active": 0,
        "weak": 0,
    }
    active_statuses = {"open", "claimed", "in_progress", "handoff", "review"}
    for task in tasks:
        summary = compliance_summary(task)
        counts[summary["status"]] = counts.get(summary["status"], 0) + 1
        task_findings: list[str] = list(summary["issues"])
        updated = _parse_stamp(task.get("updated_at"))
        if task.get("status") in active_statuses and updated and updated < stale_before:
            counts["stale_active"] += 1
            task_findings.append(f"Active task is stale by more than {stale_hours} hours.")
        current_quality_issues = task_start_quality(
            str(task.get("title") or ""),
            summary=str(task.get("intent_summary") or task.get("summary") or ""),
            paths=task.get("paths"),
        )
        weak = bool(task.get("quality_override", {}).get("allowed")) or bool(current_quality_issues)
        if weak:
            counts["weak"] += 1
            if task.get("quality_override", {}).get("allowed"):
                task_findings.append("Task was admitted with an explicit weak-quality override.")
            else:
                task_findings.append(
                    "Task does not satisfy current task-start quality rules: "
                    + " ".join(current_quality_issues)
                )
        if task_findings:
            findings.append({
                "task_id": task.get("id"),
                "agent": task.get("agent"),
                "status": task.get("status"),
                "updated_at": task.get("updated_at"),
                "memory_status": summary["status"],
                "findings": task_findings,
                "safe_actions": [
                    "append missing memory receipts to the current task",
                    "handoff or close stale work through normal lifecycle commands",
                    "preserve prior task and event history",
                ],
            })
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.isoformat(timespec="seconds"),
        "stale_hours": max(1, stale_hours),
        "counts": counts,
        "findings": findings,
    }


def write_audit_report(repo: Path, report: dict[str, Any], *, record_remediation: bool = False) -> Path:
    state = ensure_state(repo)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = state / "reports" / "memory-compliance" / f"{stamp}.json"
    write_json(path, report)
    write_json(path.parent / "latest.json", report)
    if record_remediation:
        for finding in report.get("findings") or []:
            task_id = _clean(finding.get("task_id"))
            if not task_id:
                continue
            add_event(
                repo,
                task_id,
                "memory_compliance_remediation",
                agent="system",
                message="Append-only memory compliance finding; task history unchanged.",
                data={
                    "report_path": str(path),
                    "memory_status": finding.get("memory_status"),
                    "findings": finding.get("findings") or [],
                    "safe_actions": finding.get("safe_actions") or [],
                },
            )
    return path


__all__ = [
    "RECEIPT_KINDS",
    "SCHEMA_VERSION",
    "append_receipt",
    "audit_tasks",
    "build_receipt",
    "completion_issues",
    "compliance_summary",
    "new_policy",
    "write_audit_report",
]
