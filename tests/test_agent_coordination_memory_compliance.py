# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from datetime import datetime, timedelta

import agent_runtime_paths
from agent_coordination import memory_compliance as mc


def _receipt(task_id: str, kind: str, **over):
    fields = {
        "kind": kind,
        "agent": "codex",
        "evidence": "mcp receipt readback: PASS",
    }
    fields.update(over)
    return mc.build_receipt(task_id, **fields)


def test_query_and_read_satisfy_required_policy():
    task = {"id": "t1", "memory_compliance": mc.new_policy()}
    mc.append_receipt(task, _receipt("t1", "graph_query", query="memory compliance"))
    assert mc.compliance_summary(task)["status"] == "missing"
    mc.append_receipt(
        task,
        _receipt("t1", "memory_read", store="shared-memory", memory_name="global/doctrine"),
    )
    summary = mc.compliance_summary(task)
    assert summary["status"] == "compliant"
    assert summary["receipt_count"] == 2


def test_explicit_no_relevant_memory_requires_query_reason_and_evidence():
    task = {"id": "t1", "memory_compliance": mc.new_policy()}
    mc.append_receipt(task, _receipt("t1", "graph_query", query="novel isolated typo"))
    mc.append_receipt(
        task,
        _receipt(
            "t1",
            "no_relevant_memory",
            query="novel isolated typo",
            reason="Graph returned no task-relevant source above threshold.",
        ),
    )
    assert mc.compliance_summary(task)["status"] == "compliant"


def test_write_requires_graph_refresh():
    task = {"id": "t1", "memory_compliance": mc.new_policy()}
    mc.append_receipt(task, _receipt("t1", "graph_query", query="factory doctrine"))
    mc.append_receipt(
        task,
        _receipt("t1", "memory_read", store="private-memory", memory_name="global/private"),
    )
    mc.append_receipt(
        task,
        _receipt("t1", "durable_write", store="shared-memory", memory_name="global/new"),
    )
    assert "graph refresh" in " ".join(mc.completion_issues(task)).lower()
    mc.append_receipt(task, _receipt("t1", "graph_refresh"))
    assert mc.completion_issues(task) == []


def test_legacy_task_is_reported_but_not_retroactively_blocked():
    task = {"id": "old"}
    assert mc.compliance_summary(task)["status"] == "legacy_untracked"
    assert mc.completion_issues(task) == []


def test_audit_reports_stale_and_weak_without_mutating_task():
    old = (datetime.now() - timedelta(hours=100)).isoformat(timespec="seconds")
    task = {
        "id": "t1",
        "status": "claimed",
        "updated_at": old,
        "quality_override": {"allowed": True},
        "memory_compliance": mc.new_policy(),
    }
    before = json.dumps(task, sort_keys=True)
    report = mc.audit_tasks([task], stale_hours=72)
    assert report["counts"]["stale_active"] == 1
    assert report["counts"]["weak"] == 1
    assert report["counts"]["missing"] == 1
    assert json.dumps(task, sort_keys=True) == before


def test_remediation_writes_report_and_appends_event(tmp_path, monkeypatch):
    monkeypatch.setattr(agent_runtime_paths, "COORDINATION_ROOT", tmp_path / "coordination")
    repo = tmp_path / "repo"
    repo.mkdir()
    report = mc.audit_tasks([{"id": "t1"}])
    path = mc.write_audit_report(repo, report, record_remediation=True)
    assert path.exists()
    events = list((agent_runtime_paths.state_root(repo) / "events" / "t1.jsonl").read_text(
        encoding="utf-8"
    ).splitlines())
    assert any("memory_compliance_remediation" in line for line in events)
