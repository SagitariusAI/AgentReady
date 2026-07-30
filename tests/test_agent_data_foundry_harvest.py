from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from agent_data_foundry_test_helpers import (
    base_task,
    write_task,
)

from agent_data_foundry import (
    harvest_coordination_records,
    main,
)


def test_harvest_coordination_records_backfills_multiple_roots_without_collisions(tmp_path: Path) -> None:
    coordination_root = tmp_path / "coordination"
    write_task(coordination_root, "DemoRepo-aaa", "same-id", base_task(id="same-id", agent="codex"))
    write_task(coordination_root, "DemoRepo-bbb", "same-id", base_task(id="same-id", agent="claude"))
    write_task(coordination_root, "DemoRepo-ccc", "active", base_task(id="active", status="claimed"))
    write_task(coordination_root, "DemoRepo-ddd", "broken", cast(Any, ["not", "an", "object"]))
    write_task(coordination_root, "DemoRepo-eee", "blocked", base_task(id="blocked", blockers=["missing gate evidence"]))

    first = harvest_coordination_records(tmp_path, coordination_root=coordination_root, max_roots=10, limit_per_root=10)

    assert first["schema_version"] == "agentready.data_foundry.coordination_harvest.v1"
    assert first["summary"]["roots_scanned"] == 5
    assert first["summary"]["captured"] == 3
    assert first["summary"]["skipped_ineligible"] == 1
    assert first["summary"]["skipped_invalid"] == 1
    assert first["summary"]["skipped_existing"] == 0
    assert first["summary"]["skipped_cross_lane"] == 0
    assert first["summary"]["silver_rows"] == 3
    assert first["summary"]["gold_rows"] == 3

    manifest = json.loads((tmp_path / first["manifest_path"]).read_text(encoding="utf-8"))
    assert sorted(manifest["captured_sources"]) == [
        "DemoRepo-aaa/same-id",
        "DemoRepo-bbb/same-id",
        "DemoRepo-eee/blocked",
    ]
    assert "runs/" in first["run_manifest_path"].replace("\\", "/")

    gold_path = tmp_path / first["gold_path"]
    gold_rows = [json.loads(line) for line in gold_path.read_text(encoding="utf-8").splitlines()]
    assert len(gold_rows) == 3
    assert {row["verdict"] for row in gold_rows} == {"SAFE", "NEEDS_HUMAN"}
    assert all("abstracted_agent_claim" in row for row in gold_rows)
    assert all("Raw agent summary" not in json.dumps(row) for row in gold_rows)
    assert all(row["schema_version"] == "sf.product_incident.v0.2" for row in gold_rows)
    assert all(row["dataset_family"] == "cerberus_sentinel" for row in gold_rows)
    assert all(row["training_target"] == "claim_evidence_alignment" for row in gold_rows)
    assert all(row["workflow_lane"] == "research" for row in gold_rows)
    assert all(row["data_lane"] == "research" for row in gold_rows)
    assert all(row["machinery_zone"] == "FACTORY" for row in gold_rows)
    assert all(row["dataset_readiness_level"] == "DRL-3" for row in gold_rows)
    assert all(row["provenance_type"] == "NATURAL_RECEIPT" for row in gold_rows)
    assert all(row["source_mode"] == "observed" for row in gold_rows)
    assert all(row["natural_observation"] is True for row in gold_rows)
    assert all(row["human_authored"] is False for row in gold_rows)
    assert all(row["synthetic_content"] is False for row in gold_rows)
    assert all(row["input_view"]["claim"] for row in gold_rows)
    assert all("claim_evidence_alignment" in row for row in gold_rows)
    assert all("gold_output" in row for row in gold_rows)
    assert all(row["commercial_safety"]["provider_neutral"] is True for row in gold_rows)
    assert all(row["commercial_safety"]["contains_internal_paths"] is False for row in gold_rows)
    safe_row = next(row for row in gold_rows if row["verdict"] == "SAFE")
    assert safe_row["incident_type"] == "SUPPORTED_CLAIM"
    assert safe_row["gold_output"]["required_action"] == "ALLOW_PROMOTION"
    assert safe_row["claim_evidence_alignment"]["claim_supported"] is True

    second = harvest_coordination_records(tmp_path, coordination_root=coordination_root, max_roots=10, limit_per_root=10)

    assert second["summary"]["captured"] == 0
    assert second["summary"]["skipped_existing"] == 3
    assert second["summary"]["silver_rows"] == 3
    assert second["summary"]["gold_rows"] == 3
    assert second["run_manifest_path"] != first["run_manifest_path"]


def test_harvest_requires_explicit_cross_lane_import(tmp_path: Path) -> None:
    coordination_root = tmp_path / "coordination"
    write_task(
        coordination_root,
        "DemoRepo-aaa",
        "business-task",
        base_task(id="business-task", workflow_lane="business"),
    )
    write_task(
        coordination_root,
        "DemoRepo-bbb",
        "authorized-task",
        base_task(
            id="authorized-task",
            workflow_lane="business",
            research_import_authorized=True,
        ),
    )

    result = harvest_coordination_records(tmp_path, coordination_root=coordination_root)

    assert result["summary"]["captured"] == 1
    assert result["summary"]["skipped_cross_lane"] == 1
    assert result["cross_lane_import_policy"] == "explicit_only"


def test_rebuild_removes_pre_policy_cross_lane_rows(tmp_path: Path) -> None:
    coordination_root = tmp_path / "coordination"
    write_task(
        coordination_root,
        "DemoRepo-aaa",
        "research-task",
        base_task(id="research-task", workflow_lane="research"),
    )
    first = harvest_coordination_records(tmp_path, coordination_root=coordination_root)
    gold_path = tmp_path / first["gold_path"]
    with gold_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"source_id_hash": "legacy-cross-lane"}) + "\n")

    rebuilt = harvest_coordination_records(
        tmp_path,
        coordination_root=coordination_root,
        rebuild=True,
    )

    rows = [json.loads(line) for line in (tmp_path / rebuilt["gold_path"]).read_text().splitlines()]
    assert rebuilt["rebuilt"] is True
    assert len(rows) == 1
    assert rows[0]["workflow_lane"] == "research"


def test_agent_data_foundry_cli_runs_coordination_harvest(tmp_path: Path, capsys) -> None:
    coordination_root = tmp_path / "coordination"
    write_task(coordination_root, "DemoRepo-aaa", "task-001", base_task(id="task-001"))

    exit_code = main(
        [
            "--action",
            "harvest-coordination",
            "--root",
            str(tmp_path),
            "--coordination-root",
            str(coordination_root),
            "--max-roots",
            "5",
            "--limit-per-root",
            "5",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "AgentReady Data Foundry coordination harvest" in captured.out
    assert (tmp_path / "reports" / "data-foundry" / "coordination-harvest-latest.json").exists()


def test_harvest_replaces_changed_terminal_task_snapshot(tmp_path: Path) -> None:
    coordination_root = tmp_path / "coordination"
    write_task(
        coordination_root,
        "DemoRepo-aaa",
        "task-001",
        base_task(id="task-001", status="handoff", evidence=["initial evidence"]),
    )
    first = harvest_coordination_records(tmp_path, coordination_root=coordination_root)

    write_task(
        coordination_root,
        "DemoRepo-aaa",
        "task-001",
        base_task(
            id="task-001",
            status="completed",
            evidence=["pytest passed", "git push origin feature"],
        ),
    )
    second = harvest_coordination_records(tmp_path, coordination_root=coordination_root)

    assert first["summary"]["captured"] == 1
    assert second["summary"]["captured"] == 0
    assert second["summary"]["updated"] == 1
    assert second["summary"]["gold_rows"] == 1
    gold_rows = [
        json.loads(line)
        for line in (tmp_path / second["gold_path"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(gold_rows) == 1
    assert gold_rows[0]["input_view"]["task_status"] == "completed"
    ledger = json.loads(
        (
            tmp_path
            / "data"
            / "training-library"
            / "10_working"
            / "coordination-harvest"
            / "metadata"
            / "coordination_capture_ledger.json"
        ).read_text(encoding="utf-8")
    )
    assert ledger["captured_sources"]["DemoRepo-aaa/task-001"]["version"] == 2


def test_harvest_reports_root_and_task_truncation_bounds(tmp_path: Path) -> None:
    coordination_root = tmp_path / "coordination"
    for repo in ("A-aaa", "B-bbb"):
        for index in range(3):
            write_task(
                coordination_root,
                repo,
                f"task-{index}",
                base_task(id=f"task-{index}", status="completed"),
            )
    result = harvest_coordination_records(
        tmp_path,
        coordination_root=coordination_root,
        max_roots=1,
        limit_per_root=2,
    )
    assert result["bounds"] == {
        "max_roots": 1,
        "limit_per_root": 2,
        "available_roots": 2,
        "roots_truncated": True,
        "truncated_roots_count": 1,
        "task_roots_truncated": 1,
        "truncated_tasks_count": 1,
        "truncated": True,
    }
    assert result["summary"]["tasks_seen"] == 2
