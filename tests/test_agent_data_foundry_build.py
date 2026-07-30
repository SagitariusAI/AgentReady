from __future__ import annotations

import json
from pathlib import Path

from agent_data_foundry_test_helpers import (
    base_receipt,
    write_receipt,
)

from agent_data_foundry import (
    build_data_foundry,
)


def test_build_promotes_allowed_receipts_and_rejects_training_blocked_records(tmp_path: Path) -> None:
    write_receipt(tmp_path, "accepted", base_receipt(receipt_id="accepted-001"))
    write_receipt(
        tmp_path,
        "blocked",
        base_receipt(
            receipt_id="blocked-001",
            work_product_policy="external_source_citation_only",
            dataset_format_target="instruction_jsonl",
        ),
    )

    result = build_data_foundry(tmp_path, release_id="test-release")

    assert result["summary"]["promoted"] == 1
    assert result["summary"]["rejected"] == 1
    assert result["exports"]["tool_use_jsonl"]["records"] == 1

    export_path = tmp_path / result["exports"]["tool_use_jsonl"]["path"]
    exported_rows = [json.loads(line) for line in export_path.read_text(encoding="utf-8").splitlines()]
    assert exported_rows[0]["task"] == "Implement a test fixture."
    assert exported_rows[0]["selected_tools"] == ["pytest tests/test_agent_data_foundry.py"]
    assert exported_rows[0]["metadata"]["receipt_id"] == "accepted-001"

    manifest_path = tmp_path / result["manifest_path"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["release_id"] == "test-release"
    assert manifest["summary"]["promoted"] == 1
    assert manifest["rejections"][0]["receipt_id"] == "blocked-001"
    assert "external_source_citation_only" in manifest["rejections"][0]["reasons"]


def test_build_writes_bdxl_plan_with_payload_budget_and_checksums(tmp_path: Path) -> None:
    write_receipt(
        tmp_path,
        "eval",
        base_receipt(
            receipt_id="eval-001",
            collection_purpose="evaluation",
            dataset_format_target="evaluation_jsonl",
            artifact_type="quality_self_review",
        ),
    )

    result = build_data_foundry(tmp_path, release_id="test-release")

    plan_path = tmp_path / result["bdxl_plan_path"]
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["payload_budget_bytes"] == 95_000_000_000
    assert plan["volumes"][0]["volume_id"] == "BDXL-test-release-001"
    assert plan["volumes"][0]["files"][0]["sha256"]
    assert plan["volumes"][0]["files"][0]["relative_path"].endswith("evaluation_jsonl.jsonl")
