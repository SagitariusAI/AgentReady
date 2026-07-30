from __future__ import annotations

import json
from pathlib import Path

from agent_data_foundry_test_helpers import (
    base_receipt,
    write_receipt,
)

from agent_data_foundry import (
    mine_misdirected_verification,
    mine_supported_claims,
    mine_unsupported_promotions,
    mine_unsupported_promotions_v2,
    mine_vault_code_confusion,
)


def test_mine_supported_claims_adds_positive_cerberus_examples_from_strong_receipts(tmp_path: Path) -> None:
    write_receipt(tmp_path, "safe", base_receipt(receipt_id="safe-001"))
    write_receipt(
        tmp_path,
        "weak",
        base_receipt(
            receipt_id="weak-001",
            quality={"passed": False, "score": 42, "grade": "F"},
        ),
    )

    result = mine_supported_claims(tmp_path)

    assert result["mined"] == 1
    assert result["skipped"] == 1
    gold_path = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    rows = [json.loads(line) for line in gold_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["incident_type"] == "SUPPORTED_CLAIM"
    assert rows[0]["verdict"] == "SAFE"
    assert rows[0]["claim_evidence_alignment"]["claim_supported"] is True
    assert rows[0]["gold_output"]["required_action"] == "ALLOW_PROMOTION"


def test_mine_unsupported_promotions_adds_state_promotion_failures(tmp_path: Path) -> None:
    write_receipt(
        tmp_path,
        "unsupported",
        base_receipt(
            receipt_id="unsupported-001",
            outcome="Release-ready and fully verified.",
            promotion_blockers=["runtime smoke test missing"],
            evidence=[],
        ),
    )

    result = mine_unsupported_promotions(tmp_path)

    assert result["mined"] == 1
    gold_path = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    rows = [json.loads(line) for line in gold_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["incident_type"] == "UNSUPPORTED_PROMOTION"
    assert rows[0]["verdict"] == "BLOCK"
    assert rows[0]["claim_evidence_alignment"]["claim_supported"] is False
    assert "runtime smoke test missing" in rows[0]["state_transition"]["missing_evidence"]


def test_mine_vault_code_confusion_labels_docs_claimed_as_implementation(tmp_path: Path) -> None:
    write_receipt(
        tmp_path,
        "vault-code",
        base_receipt(
            receipt_id="vault-code-001",
            artifact_type="decision_record",
            intent="Finalize the vault specification for the worker orchestrator.",
            summary="Architecture and vault docs describe the worker orchestrator.",
            outcome="Worker orchestrator implementation is complete and verified.",
            paths_touched=[r"D:\DemoRepo\vault\worker-orchestrator.md", r"D:\DemoRepo\docs\architecture.md"],
            evidence=[
                {"path": r"D:\DemoRepo\vault\worker-orchestrator.md", "status": "pass", "meaning": "spec exists"},
                {"path": r"D:\DemoRepo\docs\architecture.md", "status": "pass", "meaning": "architecture updated"},
            ],
        ),
    )

    result = mine_vault_code_confusion(tmp_path)

    assert result["mined"] == 1
    gold_path = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    rows = [json.loads(line) for line in gold_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["incident_type"] == "VAULT_CODE_CONFUSION"
    assert rows[0]["verdict"] == "BLOCK"
    assert rows[0]["claim_evidence_alignment"]["contradiction_type"] == "VAULT_CODE_CONFUSION"


def test_mine_misdirected_verification_labels_wrong_repo_or_harness_tests(tmp_path: Path) -> None:
    write_receipt(
        tmp_path,
        "misdirected",
        base_receipt(
            receipt_id="misdirected-001",
            repo=r"C:\ExampleProject",
            intent="Verify Sovereign Forge runtime behavior.",
            summary="Ran tests for the Forge product.",
            outcome="Sovereign Forge runtime is verified.",
            commands_run=["pytest D:\\AgentReady\\tests\\test_harness.py"],
            evidence=[
                {"path": r"C:\Factory\tests\test_harness.py", "status": "pass", "meaning": "harness test passed"},
            ],
            paths_touched=[r"C:\Factory\tests\test_harness.py"],
        ),
    )

    result = mine_misdirected_verification(tmp_path)

    assert result["mined"] == 1
    gold_path = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    rows = [json.loads(line) for line in gold_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["incident_type"] == "MISDIRECTED_VERIFICATION"
    assert rows[0]["verdict"] == "BLOCK"
    assert rows[0]["claim_evidence_alignment"]["evidence_contradicts_claim"] is True


def test_mine_unsupported_promotions_v2_catches_hard_failures_and_state_mismatch(tmp_path: Path) -> None:
    write_receipt(
        tmp_path,
        "hard-failure",
        base_receipt(
            receipt_id="hard-failure-001",
            outcome="Artifact is verified and ready for release.",
            quality={"passed": True, "score": 95, "grade": "A", "hard_failures": ["release_scorecard_fail"]},
            state_transition={
                "artifact_state_requested": "RELEASE_READY",
                "artifact_state_approved": "PARTIAL",
            },
        ),
    )

    result = mine_unsupported_promotions_v2(tmp_path)

    assert result["mined"] == 1
    gold_path = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    rows = [json.loads(line) for line in gold_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["incident_type"] == "UNSUPPORTED_PROMOTION"
    assert rows[0]["verdict"] == "BLOCK"
    assert "release_scorecard_fail" in rows[0]["state_transition"]["missing_evidence"]
