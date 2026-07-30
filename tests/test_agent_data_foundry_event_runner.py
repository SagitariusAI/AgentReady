# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import sys
from pathlib import Path

from agent_data_foundry_event_runner import main, run_event
from factory_capture.runner import run_command
from factory_capture.store import Store


def write_task(root: Path, task_id: str, status: str = "completed") -> None:
    path = root / "coordination" / "DemoRepo-1234" / "tasks" / f"{task_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "id": task_id,
                "status": status,
                "title": "Example terminal task",
                "workflow_lane": "research",
                "evidence": ["pytest passed", "git push origin demo"],
                "blockers": [],
            }
        ),
        encoding="utf-8",
    )


def write_receipt(root: Path, receipt_id: str) -> None:
    path = root / "coordination" / "DemoRepo-1234" / "task-reports" / receipt_id / f"{receipt_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "receipt_id": receipt_id,
                "generated_utc": "2026-06-16T00:00:00+00:00",
                "repo": r"D:\DemoRepo",
                "task_id": "task-001",
                "agent": "codex",
                "artifact_type": "execution_trace",
                "collection_scope": "repo_change",
                "collection_purpose": "training",
                "data_classification": "internal",
                "retention_class": "training_candidate_review",
                "training_value": "high",
                "work_product_policy": "company_owned_review_before_training",
                "dataset_format_target": "tool_use_jsonl",
                "future_model_should_learn": "Run the data foundry after handoff events.",
                "intent": "Verify event-triggered harvesting.",
                "summary": "A strong receipt suitable for tool-use export.",
                "outcome": "The runner harvested and built a release.",
                "confidence": 91,
                "commands_run": ["agent-data-foundry-event-runner"],
                "paths_touched": [r"D:\DemoRepo\src\demo.py"],
                "evidence": [{"path": r"D:\DemoRepo\src\demo.py", "status": "pass", "meaning": "test evidence"}],
                "changes_made": ["Created a durable export."],
                "risks": ["No known risk."],
                "next_actions": ["Use the exported row."],
                "dataset_labels": ["event-runner"],
                "quality": {"passed": True, "score": 94, "grade": "A"},
            }
        ),
        encoding="utf-8",
    )


def test_terminal_handoff_event_harvests_and_builds_when_receipts_changed(tmp_path: Path) -> None:
    write_task(tmp_path, "task-001")
    write_receipt(tmp_path, "receipt-001")

    result = run_event(
        root=tmp_path,
        event_type="handoff",
        task_id="task-001",
        force=True,
        release_prefix="event-test",
        max_roots=10,
        limit_per_root=10,
    )

    assert result["triggered"] is True
    assert result["harvest"]["summary"]["captured"] == 1
    assert result["build"]["summary"]["promoted"] == 1
    assert result["internal_training_pipeline"]["status"] == "BLOCKED_LABEL_COVERAGE"
    assert result["internal_training_pipeline"]["checks"]["train_heldout_no_overlap"] is True
    assert result["internal_training_pipeline"]["sealed_release_mutated"] is False
    candidate = result["internal_training_pipeline"]["refinery_candidate"]
    assert candidate["status"] == "CANDIDATE_BLOCKED_LABEL_COVERAGE"
    assert candidate["final_dataset_emitted"] is False
    assert result["build"]["release_id"].startswith("event-test-")
    assert (tmp_path / "reports" / "data-foundry" / "event-runner-latest.json").exists()


def test_event_runner_debounces_repeated_terminal_events(tmp_path: Path) -> None:
    write_task(tmp_path, "task-001")

    first = run_event(root=tmp_path, event_type="handoff", task_id="task-001", force=True)
    second = run_event(root=tmp_path, event_type="handoff", task_id="task-001", now=first["generated_at"])

    assert first["triggered"] is True
    assert second["triggered"] is False
    assert second["reason"] == "debounced_no_changes"


def test_force_rebuilds_pipeline_even_when_harvest_has_no_changes(tmp_path: Path) -> None:
    write_task(tmp_path, "task-001")
    first = run_event(root=tmp_path, event_type="handoff", task_id="task-001", force=True)

    second = run_event(
        root=tmp_path,
        event_type="handoff",
        task_id="task-001",
        force=True,
        now="2026-07-30T00:00:00+00:00",
    )

    assert first["internal_training_pipeline"]["status"] == "BLOCKED_LABEL_COVERAGE"
    assert second["harvest"]["summary"]["captured"] == 1
    assert second["harvest"]["rebuilt"] is True
    assert second["internal_training_pipeline"]["status"] == "BLOCKED_LABEL_COVERAGE"


def test_event_runner_does_not_debounce_a_new_terminal_task(tmp_path: Path) -> None:
    write_task(tmp_path, "task-001")
    first = run_event(root=tmp_path, event_type="handoff", task_id="task-001", force=True)

    write_task(tmp_path, "task-002")
    second = run_event(
        root=tmp_path,
        event_type="handoff",
        task_id="task-002",
        now=first["generated_at"],
    )

    assert second["triggered"] is True
    assert second["harvest"]["summary"]["captured"] == 1
    assert second["internal_training_pipeline"]["status"] == "BLOCKED_LABEL_COVERAGE"


def test_event_runner_ignores_non_terminal_events(tmp_path: Path) -> None:
    write_task(tmp_path, "task-001", status="claimed")

    result = run_event(root=tmp_path, event_type="task_started", task_id="task-001", force=True)

    assert result["triggered"] is False
    assert result["reason"] == "ignored_event_type"


def test_cli_runs_event_runner(tmp_path: Path, capsys) -> None:
    write_task(tmp_path, "task-001")

    exit_code = main(
        [
            "--root",
            str(tmp_path),
            "--event-type",
            "handoff",
            "--task-id",
            "task-001",
            "--force",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "AgentReady Data Foundry event runner" in captured.out
    assert (tmp_path / "reports" / "data-foundry" / "event-runner-latest.json").exists()


def test_event_runner_ingests_prior_governed_capture_event(tmp_path: Path) -> None:
    repo = tmp_path / "captured-repo"
    repo.mkdir()
    store = Store(repo / ".factory_capture")
    store.init(repo_root=repo)
    run_command(
        store,
        [sys.executable, "-c", "print('captured')"],
        cwd=repo,
        workflow_lane="research",
    )
    result = run_event(
        root=tmp_path,
        event_type="handoff",
        source_repo=str(repo),
        force=True,
    )
    assert result["capture_harvest"]["summary"]["captured"] == 1
    assert result["capture_harvest"]["summary"]["research_command_rows"] == 1
    assert result["internal_training_pipeline"]["dataset"]["rows_emitted"] == 1


def test_custom_coordination_root_controls_harvest_and_build_detection(tmp_path: Path) -> None:
    coordination_root = tmp_path / "external-coordination"
    external_root = coordination_root / "DemoRepo-1234"
    task_path = external_root / "tasks" / "task-001.json"
    task_path.parent.mkdir(parents=True, exist_ok=True)
    task_path.write_text(
        json.dumps(
            {
                "id": "task-001",
                "status": "completed",
                    "title": "External coordination task",
                    "workflow_lane": "research",
                "evidence": ["pytest passed"],
                "blockers": [],
            }
        ),
        encoding="utf-8",
    )
    receipt_path = external_root / "task-reports" / "receipt-001" / "receipt-001.json"
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "receipt_id": "receipt-001",
                "generated_utc": "2026-06-16T00:00:00+00:00",
                "repo": r"D:\DemoRepo",
                "task_id": "task-001",
                "agent": "codex",
                "artifact_type": "execution_trace",
                "collection_scope": "repo_change",
                "collection_purpose": "training",
                "data_classification": "internal",
                "retention_class": "training_candidate_review",
                "training_value": "high",
                "work_product_policy": "company_owned_review_before_training",
                "dataset_format_target": "retrieval_jsonl",
                "future_model_should_learn": "Honor custom coordination roots.",
                "intent": "Verify custom coordination root handling.",
                "summary": "A receipt outside the default coordination root.",
                "outcome": "The runner should harvest and build from the custom root.",
                "confidence": 90,
                "commands_run": ["agent-data-foundry-event-runner"],
                "paths_touched": [r"D:\DemoRepo\docs\note.md"],
                "evidence": [{"path": r"D:\DemoRepo\docs\note.md", "status": "pass", "meaning": "evidence"}],
                "changes_made": ["Created an external coordination receipt."],
                "risks": ["No known risk."],
                "next_actions": ["Use the exported row."],
                "dataset_labels": ["event-runner"],
                "quality": {"passed": True, "score": 94, "grade": "A"},
            }
        ),
        encoding="utf-8",
    )

    result = run_event(
        root=tmp_path,
        event_type="handoff",
        task_id="task-001",
        coordination_root=coordination_root,
        force=True,
    )

    assert result["triggered"] is True
    assert result["harvest"]["summary"]["captured"] == 1
    assert result["build"]["summary"]["promoted"] == 1
