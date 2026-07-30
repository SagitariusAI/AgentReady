# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from agent_data_foundry_test_helpers import (
    _RELEASE_DIR,
    _write_split_corpus,
    base_task,
    write_task,
)

from agent_data_foundry import (
    CLAIM_EVIDENCE_RELEASE_ARTIFACTS,
    build_claim_evidence_eval_split,
    build_claim_evidence_release_gate,
    claim_evidence_baseline_eval,
    claim_evidence_checksums_gate,
    emit_claim_evidence_checksums,
    emit_dataset_card,
    emit_label_taxonomy,
    generate_supported_claim_controlled_cases,
    harvest_coordination_records,
    promote_controlled_cases,
    upgrade_claim_evidence_gold_schema,
)


def _write_release_artifacts(release_root: Path) -> None:
    (release_root / "data").mkdir(parents=True, exist_ok=True)
    (release_root / "reports").mkdir(parents=True, exist_ok=True)
    (release_root / "dataset_card.md").write_text("## Provenance\nCONTROLLED_CASE SUPPORTED_CLAIM Natural\n", encoding="utf-8")
    (release_root / "label_taxonomy.json").write_text("{}", encoding="utf-8")
    (release_root / "data" / "eval_cases.jsonl").write_text('{"case_id": "a"}\n', encoding="utf-8")
    (release_root / "data" / "expected_outputs.jsonl").write_text('{"case_id": "a"}\n', encoding="utf-8")
    (release_root / "split_manifest.json").write_text('{"heldout_count": 1, "seed": 424242}', encoding="utf-8")
    (release_root / "reports" / "split_report.json").write_text('{"heldout_count": 1, "seed": 424242}', encoding="utf-8")
    (release_root / "reports" / "baseline_results.json").write_text('{"metrics": {"verdict_accuracy": 0.8}}', encoding="utf-8")
    (release_root / "reports" / "baseline_results.md").write_text("# baseline\n", encoding="utf-8")


def test_claim_evidence_release_gate_blocks_until_volume_and_label_requirements_pass(tmp_path: Path) -> None:
    coordination_root = tmp_path / "coordination"
    write_task(coordination_root, "DemoRepo-aaa", "safe", base_task(id="safe"))
    write_task(
        coordination_root,
        "DemoRepo-bbb",
        "no-evidence",
        base_task(id="no-evidence", evidence=[]),
    )
    harvest_coordination_records(tmp_path, coordination_root=coordination_root, max_roots=10, limit_per_root=10)

    result = build_claim_evidence_release_gate(tmp_path, product_id="claim_evidence-claim-evidence-eval-v0.1.0")

    assert result["status"] == "NOT_RELEASE_READY"
    assert result["dataset_readiness_level"] == "DRL-3"
    assert result["target_drl"] == "DRL-5"
    assert result["summary"]["total_records"] == 2
    assert result["label_distribution"]["SUPPORTED_CLAIM"] == 1
    assert result["label_distribution"]["CLAIM_WITHOUT_EVIDENCE"] == 1
    assert result["gate"]["minimum_record_count_met"]["passed"] is False
    assert result["gate"]["safe_examples_present"]["passed"] is False
    assert result["gate"]["schema_validation_passed"]["passed"] is True
    assert result["gate"]["commercial_safety_passed"]["passed"] is True

    release_root = tmp_path / "data" / "training-library" / "40_release_ready" / "claim_evidence-claim-evidence-eval-v0.1.0"
    assert (release_root / "release_gate_report.json").exists()
    assert (release_root / "README.md").exists()
    assert (tmp_path / "data" / "training-library" / "schemas" / "claim_evidence_case.schema.json").exists()


def test_upgrade_claim_evidence_gold_schema_rebuilds_legacy_rows_from_silver_sources(tmp_path: Path) -> None:
    coordination_root = tmp_path / "coordination"
    write_task(coordination_root, "DemoRepo-aaa", "safe", base_task(id="safe"))
    harvest_coordination_records(tmp_path, coordination_root=coordination_root, max_roots=10, limit_per_root=10)
    gold_path = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    gold_path.write_text(
        json.dumps(
            {
                "schema_version": "agentready.data_foundry.product_incident.v1",
                "incident_type": "PUSHED_VERIFIED",
                "verdict": "SAFE",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    result = upgrade_claim_evidence_gold_schema(tmp_path)

    rows = [json.loads(line) for line in gold_path.read_text(encoding="utf-8").splitlines()]
    assert result["rewritten"] == 1
    assert rows[0]["schema_version"] == "sf.product_incident.v0.2"
    assert rows[0]["incident_type"] == "SUPPORTED_CLAIM"
    assert rows[0]["claim_evidence_alignment"]["claim_supported"] is True


def test_upgrade_claim_evidence_gold_schema_preserves_mined_current_schema_rows_and_adds_provenance(tmp_path: Path) -> None:
    gold_path = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    gold_path.parent.mkdir(parents=True, exist_ok=True)
    current_row = {
        "schema_version": "sf.product_incident.v0.2",
        "source_id_hash": "source-hash",
        "fingerprint": "mined-row-001",
        "family": "software_factory_coordination_governance",
        "dataset_family": "claim_evidence_sentinel",
        "training_target": "claim_evidence_alignment",
        "dataset_readiness_level": "DRL-3",
        "incident_type": "MISDIRECTED_VERIFICATION",
        "verdict": "BLOCK",
        "severity": "needs_review",
        "abstracted_agent_claim": "Agent claimed a verification target that did not match the command evidence.",
        "input_view": {"claim": "verified wrong target", "claim_type": "verification_complete", "task_status": "completed", "evidence_count": 1, "blockers_present": False},
        "claim_evidence_alignment": {"claim_type": "verification_complete", "claim_supported": False, "evidence_required": ["matching_target"], "evidence_found": ["wrong_target"], "evidence_contradicts_claim": True, "contradiction_type": "MISDIRECTED_VERIFICATION"},
        "state_transition": {"artifact_state_before": "PARTIAL", "artifact_state_requested": "VERIFIED", "artifact_state_approved": "PARTIAL", "promotion_allowed": False, "missing_evidence": ["matching_target"], "promotion_denial_reason": "Verification evidence targeted the wrong artifact."},
        "quality_signal": "Mined pathology row",
        "gold_output": {"verdict": "BLOCK", "required_action": "Verify the correct target.", "model_should_learn": "Wrong-target verification is not proof."},
        "commercial_safety": {"contains_secrets": False, "contains_personal_data": False, "external_source_rights_required": False, "attorney_review_required_for_paid_release": True},
        "evidence_profile": {"gate_evidence_present": True, "push_evidence_present": False, "blockers_present": False, "evidence_count": 1},
        "recommended_use": ["internal_eval"],
    }
    gold_path.write_text(json.dumps(current_row) + "\n", encoding="utf-8")

    result = upgrade_claim_evidence_gold_schema(tmp_path)

    rows = [json.loads(line) for line in gold_path.read_text(encoding="utf-8").splitlines()]
    assert result["rewritten"] == 1
    assert result["preserved_current_schema_rows"] == 1
    assert rows[0]["incident_type"] == "MISDIRECTED_VERIFICATION"
    assert rows[0]["provenance_type"] == "NATURAL_RECEIPT"
    assert rows[0]["source_mode"] == "observed"
    assert rows[0]["natural_observation"] is True
    assert rows[0]["human_authored"] is False


def test_release_gate_explicitly_blocks_negative_only_corpus(tmp_path: Path) -> None:
    coordination_root = tmp_path / "coordination"
    write_task(coordination_root, "DemoRepo-aaa", "no-evidence", base_task(id="no-evidence", evidence=[]))
    harvest_coordination_records(tmp_path, coordination_root=coordination_root, max_roots=10, limit_per_root=10)

    result = build_claim_evidence_release_gate(tmp_path)

    assert result["label_distribution"]["CLAIM_WITHOUT_EVIDENCE"] == 1
    assert result["gate"]["negative_only_corpus_blocked"]["passed"] is False


def test_release_gate_packaging_checks_reflect_real_emission(tmp_path: Path) -> None:
    generate_supported_claim_controlled_cases(tmp_path)
    promote_controlled_cases(tmp_path)

    gate_before = build_claim_evidence_release_gate(tmp_path)
    assert gate_before["gate"]["dataset_card_present"]["passed"] is False
    assert gate_before["gate"]["label_taxonomy_present"]["passed"] is False

    emit_label_taxonomy(tmp_path)
    emit_dataset_card(tmp_path)
    gate_after = build_claim_evidence_release_gate(tmp_path)

    assert gate_after["gate"]["dataset_card_present"]["passed"] is True
    assert gate_after["gate"]["label_taxonomy_present"]["passed"] is True
    # Emitting the card and taxonomy must NOT flip the release: the remaining
    # packaging gates (split, baseline, checksums) keep it NOT_RELEASE_READY.
    assert gate_after["status"] == "NOT_RELEASE_READY"
    assert gate_after["gate"]["train_validation_test_split_present"]["passed"] is False
    assert gate_after["gate"]["baseline_eval_present"]["passed"] is False
    assert gate_after["gate"]["checksums_present"]["passed"] is False


def test_release_gate_split_check_reflects_real_emission(tmp_path: Path) -> None:
    _write_split_corpus(tmp_path)

    gate_before = build_claim_evidence_release_gate(tmp_path)
    assert gate_before["gate"]["train_validation_test_split_present"]["passed"] is False

    build_claim_evidence_eval_split(tmp_path)
    gate_after = build_claim_evidence_release_gate(tmp_path)
    assert gate_after["gate"]["train_validation_test_split_present"]["passed"] is True
    # Split alone does not flip the release: baseline + checksums remain.
    assert gate_after["status"] == "NOT_RELEASE_READY"
    assert gate_after["gate"]["baseline_eval_present"]["passed"] is False
    assert gate_after["gate"]["checksums_present"]["passed"] is False


def test_release_gate_baseline_check_reflects_real_emission(tmp_path: Path) -> None:
    _write_split_corpus(tmp_path)
    build_claim_evidence_eval_split(tmp_path)

    gate_before = build_claim_evidence_release_gate(tmp_path)
    assert gate_before["gate"]["baseline_eval_present"]["passed"] is False

    claim_evidence_baseline_eval(tmp_path)
    gate_after = build_claim_evidence_release_gate(tmp_path)
    assert gate_after["gate"]["baseline_eval_present"]["passed"] is True
    # Baseline alone must not flip the release: checksums still seal it.
    assert gate_after["status"] == "NOT_RELEASE_READY"
    assert gate_after["gate"]["checksums_present"]["passed"] is False


def test_claim_evidence_checksums_gate_validates_coverage_and_freshness(tmp_path: Path) -> None:
    release_root = tmp_path / _RELEASE_DIR
    _write_release_artifacts(release_root)

    # No checksums yet -> gate check fails.
    assert claim_evidence_checksums_gate(release_root)[0] is False

    emit_claim_evidence_checksums(tmp_path)
    assert claim_evidence_checksums_gate(release_root)[0] is True

    # Tampering with a sealed artifact makes the checksums stale -> fail.
    (release_root / "dataset_card.md").write_text("## Provenance\nCONTROLLED_CASE SUPPORTED_CLAIM Natural TAMPERED\n", encoding="utf-8")
    passed, _message, detail = claim_evidence_checksums_gate(release_root)
    assert passed is False
    assert any("dataset_card.md" in entry for entry in detail.get("stale_or_missing", []))


def test_claim_evidence_checksums_gate_fails_when_an_artifact_is_missing(tmp_path: Path) -> None:
    release_root = tmp_path / _RELEASE_DIR
    _write_release_artifacts(release_root)
    emit_claim_evidence_checksums(tmp_path)
    (release_root / "reports" / "baseline_results.json").unlink()

    passed, _message, detail = claim_evidence_checksums_gate(release_root)
    assert passed is False


def test_emit_claim_evidence_checksums_writes_sealed_receipt_without_self_hashing(tmp_path: Path) -> None:
    release_root = tmp_path / _RELEASE_DIR
    _write_release_artifacts(release_root)

    emit_claim_evidence_checksums(tmp_path)

    sums = (release_root / "checksums" / "sha256sums.txt").read_text(encoding="utf-8")
    for relpath in CLAIM_EVIDENCE_RELEASE_ARTIFACTS:
        assert relpath in sums
    # The seal must not hash the gate report or itself into a circular pretzel.
    assert "release_gate_report.json" not in sums
    assert "sha256sums.txt" not in sums
    assert "release_receipt.json" not in sums

    receipt = json.loads((release_root / "release_receipt.json").read_text(encoding="utf-8"))
    assert receipt["dataset_id"] == "claim_evidence-claim-evidence-eval"
    assert receipt["version"] == "0.1.0"
    assert receipt["commercial_clearance"] == "NOT_ATTORNEY_REVIEWED"
    assert receipt["owner_release_required"] is True
    assert "gate_pass_count" in receipt
    assert "split_seed" in receipt
