# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from agent_data_foundry_test_helpers import (
    _DATASET_DIR,
    _write_dataset_gold,
)

from agent_data_foundry import (
    build_curated_dataset,
    data_rights_gate,
    default_data_need,
    default_data_rights,
    infer_data_need_from_incident,
    infer_data_rights_from_record,
    main,
    validate_data_need,
    validate_data_rights,
)


def _graded_dataset(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "dataset.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def _row(grade: str, technical_value: str = "HIGH", **rights_over) -> dict:
    return {
        "fingerprint": f"fp-{grade}",
        "data_need": default_data_need(technical_value=technical_value),
        "data_rights": default_data_rights(grade=grade, **rights_over),
    }


def test_valid_data_need_passes() -> None:
    assert validate_data_need(default_data_need()) == []
    rich = default_data_need(
        primary_need="CLAIM_EVIDENCE_ALIGNMENT",
        technical_value="HIGH",
        value_reason="Unsupported completion claim with blockers present.",
        secondary_needs=["CLAIM_EVIDENCE_SENTINEL_TRAINING"],
        future_model_should_learn=["Completion requires evidence."],
        recommended_internal_use=["internal_eval", "sentinel_training"],
    )
    assert validate_data_need(rich) == []


def test_invalid_primary_need_fails() -> None:
    bad = default_data_need(primary_need="SELL_EVERYTHING_NOW")
    assert "data_need.primary_need:invalid" in validate_data_need(bad)


def test_invalid_technical_value_fails() -> None:
    bad = default_data_need(technical_value="PRICELESS")
    assert "data_need.technical_value:invalid" in validate_data_need(bad)


def test_valid_data_rights_passes() -> None:
    assert validate_data_rights(default_data_rights()) == []


def test_unknown_or_mixed_record_defaults_to_restricted_use() -> None:
    rights = infer_data_rights_from_record({"incident_type": "CLAIM_WITHOUT_EVIDENCE"})
    assert rights["grade"] == "A_INTERNAL_RESEARCH_ONLY"
    assert rights["export_allowed"] is False
    assert rights["commercial_sale_allowed"] is False
    assert rights["requires_legal_review"] is True
    assert rights["requires_owner_release"] is True
    assert validate_data_rights(rights) == []


def test_quarantine_flags_force_grade_f() -> None:
    rights = infer_data_rights_from_record({
        "incident_type": "SUPPORTED_CLAIM",
        "commercial_safety": {"provider_neutral": False, "contains_secrets": True},
    })
    assert rights["grade"] == "F_QUARANTINE"
    assert rights["export_allowed"] is False
    assert rights["external_eval_allowed"] is False
    assert rights["external_training_allowed"] is False
    assert rights["commercial_sale_allowed"] is False
    assert validate_data_rights(rights) == []


def test_critical_technical_value_does_not_imply_export() -> None:
    # A CRITICAL-value, provider-neutral, release-eligible record -> at most an
    # external-EVAL candidate; export and sale stay False (high value != sellable).
    record = {
        "incident_type": "MISDIRECTED_VERIFICATION",
        "release_eligible": True,
        "commercial_safety": {"provider_neutral": True, "contains_raw_provider_output": False, "release_eligible": True},
    }
    need = infer_data_need_from_incident(record)
    rights = infer_data_rights_from_record(record)
    assert need["technical_value"] == "CRITICAL"
    assert rights["export_allowed"] is False
    assert rights["commercial_sale_allowed"] is False
    assert validate_data_rights(rights) == []


def test_external_training_candidate_requires_explicit_license_evidence() -> None:
    # Without license evidence, a record never infers an external-training grade.
    no_license = infer_data_rights_from_record({
        "incident_type": "SUPPORTED_CLAIM",
        "release_eligible": True,
        "commercial_safety": {"provider_neutral": True, "contains_raw_provider_output": False, "release_eligible": True},
    })
    assert no_license["grade"] == "C_EXTERNAL_EVAL_CANDIDATE"
    assert no_license["external_training_allowed"] is False

    # With explicit license evidence, it may become a D candidate (still gated).
    with_license = infer_data_rights_from_record({
        "incident_type": "SUPPORTED_CLAIM",
        "release_eligible": True,
        "license_evidence_path": "data/licenses/apache_2_0.txt",
        "commercial_safety": {"provider_neutral": True, "contains_raw_provider_output": False, "release_eligible": True},
    })
    assert with_license["grade"] == "D_EXTERNAL_TRAINING_CANDIDATE"
    assert with_license["external_training_allowed"] is True
    assert validate_data_rights(with_license) == []

    # The validator rejects external_training_allowed without license evidence.
    forged = default_data_rights(grade="D_EXTERNAL_TRAINING_CANDIDATE", external_training_allowed=True, external_eval_allowed=True)
    assert "data_rights.external_training_allowed:requires_license_evidence" in validate_data_rights(forged)


def test_incident_to_need_mapping_and_unknown_fallback() -> None:
    assert infer_data_need_from_incident({"incident_type": "MISDIRECTED_VERIFICATION"})["technical_value"] == "CRITICAL"
    assert infer_data_need_from_incident({"incident_type": "SUPPORTED_CLAIM"})["primary_need"] == "CLAIM_EVIDENCE_ALIGNMENT"
    unknown = infer_data_need_from_incident({"incident_type": "SOMETHING_NEW"})
    assert unknown["primary_need"] == "FACTORY_DATASET_INTERNAL"
    assert unknown["technical_value"] == "MEDIUM"
    assert validate_data_need(unknown) == []


def test_validate_data_rights_blocks_inconsistent_commercial_sale() -> None:
    # Commercial sale cannot be true while owner/legal review is still required.
    bad = default_data_rights(grade="D_EXTERNAL_TRAINING_CANDIDATE", commercial_sale_allowed=True)
    failures = validate_data_rights(bad)
    assert any("commercial_sale_allowed" in f for f in failures)


def test_internal_research_passes_for_dataset_rows(tmp_path: Path) -> None:
    _write_dataset_gold(tmp_path)
    build_curated_dataset(tmp_path)
    report = data_rights_gate(tmp_path, intended_use="internal_research")
    assert report["status"] == "PASS"
    assert report["rows_failed"] == 0
    assert report["export_allowed_rows"] == 0


def test_external_eval_rejects_dataset_because_export_not_cleared(tmp_path: Path) -> None:
    _write_dataset_gold(tmp_path)
    build_curated_dataset(tmp_path)
    report = data_rights_gate(tmp_path, intended_use="external_eval")
    # Dataset rows are grade C but export_allowed=false -> candidate, not cleared.
    assert report["status"] == "FAIL"
    assert "export_allowed_false" in report["failure_reasons"]


def test_external_eval_passes_only_with_export_and_clearance(tmp_path: Path) -> None:
    good = _row("C_EXTERNAL_EVAL_CANDIDATE", export_allowed=True, external_eval_allowed=True,
                provider_neutral=True, requires_legal_review=False, requires_owner_release=False)
    report = data_rights_gate(tmp_path, dataset_path=_graded_dataset(tmp_path, [good]), intended_use="external_eval")
    assert report["status"] == "PASS"


def test_external_training_rejects_c_rows_even_if_export_true(tmp_path: Path) -> None:
    c_row = _row("C_EXTERNAL_EVAL_CANDIDATE", export_allowed=True, external_eval_allowed=True,
                 provider_neutral=True, requires_legal_review=False, requires_owner_release=False)
    report = data_rights_gate(tmp_path, dataset_path=_graded_dataset(tmp_path, [c_row]), intended_use="external_training")
    assert report["status"] == "FAIL"
    assert any("not_eligible_for_external_training" in k for k in report["failure_reasons"])


def test_external_training_accepts_only_d_with_license_and_clearance(tmp_path: Path) -> None:
    d_row = _row("D_EXTERNAL_TRAINING_CANDIDATE", export_allowed=True, external_training_allowed=True,
                 external_eval_allowed=True, provider_neutral=True, license_evidence_path="data/licenses/apache.txt",
                 requires_legal_review=False, requires_owner_release=False)
    ok = data_rights_gate(tmp_path, dataset_path=_graded_dataset(tmp_path, [d_row]), intended_use="external_training")
    assert ok["status"] == "PASS"
    # Same D row without license evidence fails.
    no_license = _row("D_EXTERNAL_TRAINING_CANDIDATE", export_allowed=True, external_training_allowed=True,
                      provider_neutral=True, requires_legal_review=False, requires_owner_release=False)
    bad = data_rights_gate(tmp_path, dataset_path=_graded_dataset(tmp_path, [no_license]), intended_use="external_training")
    assert bad["status"] == "FAIL"
    assert "missing_license_evidence" in bad["failure_reasons"]


def test_commercial_sale_rejects_rows_without_clearance(tmp_path: Path) -> None:
    pending = _row("D_EXTERNAL_TRAINING_CANDIDATE", export_allowed=True, commercial_sale_allowed=True,
                   requires_legal_review=True, requires_owner_release=True)
    report = data_rights_gate(tmp_path, dataset_path=_graded_dataset(tmp_path, [pending]), intended_use="commercial_sale")
    assert report["status"] == "FAIL"
    assert any("pending" in k for k in report["failure_reasons"])


def test_quarantine_fails_every_intended_use(tmp_path: Path) -> None:
    q = _row("F_QUARANTINE")
    for use in ("internal_research", "internal_training", "external_eval", "external_training", "commercial_sale"):
        report = data_rights_gate(tmp_path, dataset_path=_graded_dataset(tmp_path, [q]), intended_use=use)
        assert report["status"] == "FAIL", use


def test_critical_technical_value_cannot_bypass_rights(tmp_path: Path) -> None:
    # CRITICAL technical value but only internal-research grade -> still fails external_eval.
    critical_internal = _row("A_INTERNAL_RESEARCH_ONLY", technical_value="CRITICAL")
    report = data_rights_gate(tmp_path, dataset_path=_graded_dataset(tmp_path, [critical_internal]), intended_use="external_eval")
    assert report["status"] == "FAIL"
    assert critical_internal["data_need"]["technical_value"] == "CRITICAL"


def test_missing_data_rights_fails(tmp_path: Path) -> None:
    row = {"fingerprint": "fp-x", "data_need": default_data_need()}
    report = data_rights_gate(tmp_path, dataset_path=_graded_dataset(tmp_path, [row]), intended_use="internal_research")
    assert report["status"] == "FAIL"
    assert "missing_data_rights" in report["failure_reasons"]


def test_missing_data_need_fails(tmp_path: Path) -> None:
    row = {"fingerprint": "fp-y", "data_rights": default_data_rights()}
    report = data_rights_gate(tmp_path, dataset_path=_graded_dataset(tmp_path, [row]), intended_use="internal_research")
    assert report["status"] == "FAIL"
    assert "missing_data_need" in report["failure_reasons"]


def test_cli_data_rights_gate_action(tmp_path: Path, capsys) -> None:
    _write_dataset_gold(tmp_path)
    build_curated_dataset(tmp_path)
    exit_code = main(["--action", "data-rights-gate", "--root", str(tmp_path), "--intended-use", "internal_research"])
    assert exit_code == 0
    assert "data rights gate" in capsys.readouterr().out
    assert (tmp_path / _DATASET_DIR / "data_rights_gate_report.json").exists()
