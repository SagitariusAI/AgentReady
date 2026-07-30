# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from agent_data_foundry import (
    baseline_sentinel_predict,
    build_curated_dataset,
    claim_evidence_sentinel_baseline_eval,
    claim_evidence_sentinel_export_root,
    export_claim_evidence_sentinel_training,
    harvest_coordination_records,
    jsonl_row_count,
    read_jsonl,
)


def _dataset_export_row(incident: str, fingerprint: str, *, grade: str = "A_INTERNAL_RESEARCH_ONLY",
                     gold_verdict: str = "BLOCK", claim: str = "A factory agent claimed a state transition.") -> dict:
    return {
        "incident_type": incident, "fingerprint": fingerprint, "source_id_hash": "h" + fingerprint,
        "verdict": "SUSPICIOUS", "provenance_type": "NATURAL_RECEIPT", "abstracted_agent_claim": claim,
        "input_view": {"claim": claim, "claim_type": "governed_task_state_transition", "task_status": "closed",
                       "evidence_count": 3, "blockers_present": False},
        "evidence_profile": {"evidence_count": 3, "gate_evidence_present": True, "push_evidence_present": False, "blockers_present": False},
        "claim_evidence_alignment": {"evidence_contradicts_claim": True, "contradiction_type": incident,
                                     "evidence_required": ["quality_gate_pass", "push_receipt"]},
        "gold_output": {"verdict": gold_verdict, "required_action": "REJECT_PROMOTION", "model_should_learn": "x"},
        "data_rights": {"grade": grade, "export_allowed": False, "commercial_sale_allowed": False},
    }


def _write_dataset_internal(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "data" / "training-library" / "30_curated" / "internal" / "factory-dataset" / "curated_dataset_internal.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def _export_all_rows(tmp_path: Path) -> list[dict]:
    out = claim_evidence_sentinel_export_root(tmp_path)
    return (read_jsonl(out / "sft_train.jsonl") + read_jsonl(out / "classification_train.jsonl")
            + read_jsonl(out / "heldout_eval.jsonl"))


def _provenance_manifest(tmp_path: Path) -> dict:
    return json.loads((claim_evidence_sentinel_export_root(tmp_path) / "provenance_manifest.json").read_text(encoding="utf-8"))


def _heldout_row(label: str, verdict: str, *, contradicts: bool = False, blockers: bool = False,
                 gate: bool = True, push: bool = True) -> dict:
    input_text = "\n".join([
        "CLAIM: x", "CLAIM_TYPE: t", "TASK_STATUS: closed", "EVIDENCE_COUNT: 3",
        f"GATE_EVIDENCE_PRESENT: {gate}", f"PUSH_EVIDENCE_PRESENT: {push}",
        f"BLOCKERS_PRESENT: {blockers}", f"EVIDENCE_CONTRADICTS_CLAIM: {contradicts}",
    ])
    return {
        "input": input_text, "label": label,
        "expected": {"verdict": verdict, "labels": [label], "evidence": [], "risk_score": 0, "required_action": ""},
        "metadata": {"source_pool": "curated_dataset", "data_rights_grade": "C_EXTERNAL_EVAL_CANDIDATE"},
    }


def _write_heldout(tmp_path: Path, rows: list[dict]) -> Path:
    p = claim_evidence_sentinel_export_root(tmp_path) / "heldout_eval.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def test_export_claim_evidence_sentinel_training(tmp_path: Path) -> None:
    rows = [_dataset_export_row("CLAIM_WITHOUT_EVIDENCE", f"cwe{i}", gold_verdict="BLOCK") for i in range(12)]
    rows += [_dataset_export_row("SUPPORTED_CLAIM", f"sc{i}", gold_verdict="ALLOW") for i in range(8)]
    rows += [_dataset_export_row("COMPLETION_BY_DEFERRAL", f"cbd{i}", gold_verdict="HUMAN_REVIEW") for i in range(6)]
    rows.append(_dataset_export_row("CLAIM_WITHOUT_EVIDENCE", "q1", grade="F_QUARANTINE"))  # excluded
    rows.append(_dataset_export_row("QUARANTINE_REVIEW", "off1"))  # off-target label excluded
    _write_dataset_internal(tmp_path, rows)

    result = export_claim_evidence_sentinel_training(tmp_path, heldout_pct=20)
    out = claim_evidence_sentinel_export_root(tmp_path)
    for name in ("sft_train.jsonl", "classification_train.jsonl", "heldout_eval.jsonl",
                 "export_manifest.json", "rights_report.json", "split_manifest.json"):
        assert (out / name).exists()
    assert result["readback_matches"] is True
    assert result["train_heldout_no_overlap"] is True
    assert result["all_restricted_use"] is True
    assert result["model_training_performed"] is False
    assert result["excluded"]["quarantine"] == 1
    assert result["excluded"]["off_target_label"] == 1
    assert result["train_count"] + result["heldout_count"] == 26  # 12 + 8 + 6
    assert result["status"] == "CURATED_PARTIAL_LABEL_COVERAGE"
    assert result["broad_label_readiness"] is False
    assert "VAULT_CODE_CONFUSION" in result["unsupported_labels"]
    assert set(result["label_coverage"]) == {
        "CLAIM_WITHOUT_EVIDENCE",
        "COMPLETION_BY_DEFERRAL",
        "MISDIRECTED_VERIFICATION",
        "UNSUPPORTED_PROMOTION",
        "SUPPORTED_CLAIM",
        "VAULT_CODE_CONFUSION",
    }
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()


def test_label_coverage_preserves_controlled_case_provenance(tmp_path: Path) -> None:
    controlled = _dataset_export_row("VAULT_CODE_CONFUSION", "controlled-vcc")
    controlled["provenance_type"] = "CONTROLLED_CASE"
    _write_dataset_internal(tmp_path, [controlled])
    result = export_claim_evidence_sentinel_training(tmp_path, heldout_pct=0)
    support = result["label_coverage"]["VAULT_CODE_CONFUSION"]
    assert support["total"] == 1
    assert support["provenance"] == {"CONTROLLED_CASE": 1}
    assert result["broad_label_readiness"] is False


def test_export_lineage_manifest_resolves_coordination_bronze_ledger(tmp_path: Path) -> None:
    task = tmp_path / "coordination" / "Demo-1" / "tasks" / "task-1.json"
    task.parent.mkdir(parents=True)
    task.write_text(
        json.dumps(
            {
                "id": "task-1",
                "status": "completed",
                "workflow_lane": "research",
                "evidence": ["pytest passed", "git push origin branch"],
                "blockers": [],
            }
        ),
        encoding="utf-8",
    )
    harvest_coordination_records(tmp_path, max_roots=10, limit_per_root=10)
    build_curated_dataset(tmp_path)
    result = export_claim_evidence_sentinel_training(tmp_path, heldout_pct=0)
    manifest = json.loads((tmp_path / result["lineage_manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["row_count"] == 1
    lineage = manifest["rows"][0]["source_lineage"]
    assert lineage["provenance_type"] == "COORDINATION_TASK"
    assert lineage["bronze_path"].endswith(".json")
    assert lineage["ledger_path"].endswith("coordination_capture_ledger.json")


def test_sft_format_strict_sentinel_json(tmp_path: Path) -> None:
    rows = [_dataset_export_row("CLAIM_WITHOUT_EVIDENCE", f"cwe{i}", gold_verdict="BLOCK") for i in range(10)]
    rows += [_dataset_export_row("SUPPORTED_CLAIM", f"sc{i}", gold_verdict="ALLOW") for i in range(10)]
    _write_dataset_internal(tmp_path, rows)
    export_claim_evidence_sentinel_training(tmp_path)
    out = claim_evidence_sentinel_export_root(tmp_path)
    sft = read_jsonl(out / "sft_train.jsonl")
    assert sft
    roles = [m["role"] for m in sft[0]["messages"]]
    assert roles == ["system", "user", "assistant"]
    payload = json.loads(sft[0]["messages"][2]["content"])  # strict JSON output
    assert set(payload) == {"verdict", "labels", "evidence", "risk_score", "required_action"}
    assert payload["verdict"] in ("SAFE", "BLOCK", "NEEDS_HUMAN")
    cls = read_jsonl(out / "classification_train.jsonl")
    by_label = {r["label"]: r["verdict"] for r in cls}
    assert by_label.get("SUPPORTED_CLAIM") == "SAFE"  # gold ALLOW -> SAFE
    assert by_label.get("CLAIM_WITHOUT_EVIDENCE") == "BLOCK"  # gold BLOCK -> BLOCK


def test_export_deterministic_split_no_overlap(tmp_path: Path) -> None:
    rows = [_dataset_export_row("CLAIM_WITHOUT_EVIDENCE", f"r{i}", gold_verdict="BLOCK") for i in range(40)]
    _write_dataset_internal(tmp_path, rows)
    out = claim_evidence_sentinel_export_root(tmp_path)
    r1 = export_claim_evidence_sentinel_training(tmp_path, heldout_pct=25)
    sft1 = (out / "sft_train.jsonl").read_text(encoding="utf-8")
    eval1 = (out / "heldout_eval.jsonl").read_text(encoding="utf-8")
    r2 = export_claim_evidence_sentinel_training(tmp_path, heldout_pct=25)
    assert (out / "sft_train.jsonl").read_text(encoding="utf-8") == sft1  # deterministic
    assert (out / "heldout_eval.jsonl").read_text(encoding="utf-8") == eval1
    assert r1["train_count"] > 0 and r1["heldout_count"] > 0 and r2["train_heldout_no_overlap"] is True
    # train and heldout source keys are disjoint
    train_keys = {r["metadata"]["source_id_hash"] for r in read_jsonl(out / "classification_train.jsonl")}
    heldout_keys = {r["metadata"]["source_id_hash"] for r in read_jsonl(out / "heldout_eval.jsonl")}
    assert train_keys.isdisjoint(heldout_keys)


def test_export_excludes_leak_and_emits_no_secret(tmp_path: Path) -> None:
    token = "ghp_" + "ab" * 18  # real-looking, built at runtime
    rows = [_dataset_export_row("CLAIM_WITHOUT_EVIDENCE", f"r{i}", gold_verdict="BLOCK") for i in range(5)]
    rows.append(_dataset_export_row("CLAIM_WITHOUT_EVIDENCE", "leak1", gold_verdict="BLOCK", claim=f"the token is {token}"))
    _write_dataset_internal(tmp_path, rows)
    result = export_claim_evidence_sentinel_training(tmp_path)
    assert result["excluded"]["leak"] >= 1  # the leak row was dropped
    out = claim_evidence_sentinel_export_root(tmp_path)
    blob = (out / "sft_train.jsonl").read_text(encoding="utf-8") + (out / "heldout_eval.jsonl").read_text(encoding="utf-8")
    assert token not in blob and ("ab" * 18) not in blob


def test_export_paired_curriculum_envelope_on_rows(tmp_path: Path) -> None:
    rows = [_dataset_export_row("SUPPORTED_CLAIM", f"sc{i}", gold_verdict="ALLOW") for i in range(6)]
    rows += [_dataset_export_row("CLAIM_WITHOUT_EVIDENCE", f"cwe{i}", gold_verdict="BLOCK") for i in range(6)]
    rows += [_dataset_export_row("MISDIRECTED_VERIFICATION", f"mv{i}", gold_verdict="BLOCK") for i in range(4)]
    _write_dataset_internal(tmp_path, rows)
    result = export_claim_evidence_sentinel_training(tmp_path)
    out = claim_evidence_sentinel_export_root(tmp_path)
    sft = read_jsonl(out / "sft_train.jsonl")
    cls = read_jsonl(out / "classification_train.jsonl")
    ev = read_jsonl(out / "heldout_eval.jsonl")
    everything = sft + cls + ev
    assert everything
    for r in everything:
        lo = r["paired_curriculum"]
        assert lo["schema_version"] == "sf.paired_curriculum_curriculum.v0.1"
        assert lo["pair_id"].startswith("paired_curriculum-pair-") and lo["sign"] in ("+", "-")
        assert lo["grade"] in ("G3", "G4", "G5", "G6", "G7") and lo["lang"] == "EN"
        assert lo["meta"]["rights_scope"] == "restricted_use" and lo["meta"]["curriculum"] == "PairedCurriculum"
        assert set(lo["insufficiency"]) == {"kind", "repair_target"} and lo["overlay"]["kind"] == "NONE"

    def lo_for(label: str) -> dict:
        for r in everything:
            inc = r.get("label") or (r.get("metadata") or {}).get("incident_type")
            if inc == label:
                return r["paired_curriculum"]
        raise AssertionError(label)

    sc, cwe, mv = lo_for("SUPPORTED_CLAIM"), lo_for("CLAIM_WITHOUT_EVIDENCE"), lo_for("MISDIRECTED_VERIFICATION")
    assert sc["sign"] == "+" and sc["anchors"] == ["EVIDENCE", "ROUNDTRIP"] and sc["insufficiency"]["kind"] is None
    assert cwe["sign"] == "-" and cwe["anchors"] == ["EVIDENCE", "BOOLEAN"] and cwe["insufficiency"]["kind"] == "missing_evidence"
    assert mv["sign"] == "-" and mv["anchors"] == ["TOOL_TARGET", "WORKFLOW"]
    assert mv["workflow_spine"] == ["task", "tool_selection", "verification", "verdict"]
    # signed-pair family: stable, deterministic pair_id; evidence_claim is paired, verification_target is not
    assert sc["pair_id"] == cwe["pair_id"] == "paired_curriculum-pair-evidence_claim"
    assert sc["pair_status"] == "paired" and cwe["pair_status"] == "paired"
    assert mv["pair_status"] == "unpaired"

    man = json.loads((out / "curriculum_manifest.json").read_text(encoding="utf-8"))
    assert man["rows_with_paired_curriculum"] == result["rows_with_paired_curriculum"]
    assert man["sign_distribution"].get("+", 0) >= 1 and man["sign_distribution"].get("-", 0) >= 1
    assert "EVIDENCE" in man["anchor_distribution"] and man["pair_id_count"] >= 1
    assert man["all_restricted_use"] is True
    em = json.loads((out / "export_manifest.json").read_text(encoding="utf-8"))
    assert em["curriculum"] == "PairedCurriculum" and em["paired_curriculum_curriculum"]["rows_with_paired_curriculum"] == result["rows_with_paired_curriculum"]


def test_provenance_present_on_every_exported_row(tmp_path: Path) -> None:
    rows = [_dataset_export_row("CLAIM_WITHOUT_EVIDENCE", f"cwe{i}", gold_verdict="BLOCK") for i in range(10)]
    rows += [_dataset_export_row("SUPPORTED_CLAIM", f"sc{i}", gold_verdict="ALLOW") for i in range(8)]
    _write_dataset_internal(tmp_path, rows)
    export_claim_evidence_sentinel_training(tmp_path, source_commit="deadbeefcommit")
    everything = _export_all_rows(tmp_path)
    assert everything
    for r in everything:
        cp = r["creator_provenance"]
        assert cp["schema_version"] == "sf.creator_provenance.v0.1"
        assert isinstance(r["provenance_chain"], list) and r["provenance_chain"]  # required, non-empty
        assert r["review_provenance"]["schema_version"] == "sf.review_provenance.v0.1"
        assert r["provenance_chain"][-1]["stage"] == "exported"  # terminal export stage always present
        assert r["provenance_chain"][-1]["creator_type"] == "deterministic_factory"


def test_provenance_exporter_is_factory_with_commit(tmp_path: Path) -> None:
    rows = [_dataset_export_row("CLAIM_WITHOUT_EVIDENCE", f"r{i}", gold_verdict="BLOCK") for i in range(6)]
    _write_dataset_internal(tmp_path, rows)
    export_claim_evidence_sentinel_training(tmp_path, source_commit="commitsha123")
    for r in _export_all_rows(tmp_path):
        cp = r["creator_provenance"]
        assert cp["creator_display"] == "AgentReady Factory" and cp["creator_type"] == "deterministic_factory"
        assert cp["source_commit"] == "commitsha123" and cp["provider"] == "agentready_factory"
    man = _provenance_manifest(tmp_path)
    assert man["source_commit"] == "commitsha123"
    assert man["source_commit_distribution"] == {"commitsha123": man["row_count"]}


def test_provenance_owner_correction_stage_when_explicit(tmp_path: Path) -> None:
    rows = [_dataset_export_row("CLAIM_WITHOUT_EVIDENCE", f"r{i}", gold_verdict="BLOCK") for i in range(4)]
    corrected = _dataset_export_row("CLAIM_WITHOUT_EVIDENCE", "fix1", gold_verdict="BLOCK")
    corrected["owner_override_reason"] = "Owner overrode the sentinel verdict after reviewing the push receipt."
    rows.append(corrected)
    _write_dataset_internal(tmp_path, rows)
    export_claim_evidence_sentinel_training(tmp_path, source_commit="c1")
    fix_rows = [r for r in _export_all_rows(tmp_path) if (r.get("metadata") or {}).get("source_id_hash") == "hfix1"]
    assert fix_rows
    for r in fix_rows:
        corrected_stages = [s for s in r["provenance_chain"] if s["stage"] == "corrected"]
        assert corrected_stages, "explicit owner correction must add a corrected stage"
        assert corrected_stages[0]["creator_type"] == "human" and corrected_stages[0]["authority_level"] == "owner"
        assert r["review_provenance"]["review_status"] == "owner_approved"
        assert any(rv["authority_level"] == "owner" for rv in r["review_provenance"]["reviewers"])
    man = _provenance_manifest(tmp_path)
    assert man["owner_corrected_count"] >= 1 and man["owner_approved_training_gold_count"] >= 1


def test_provenance_model_name_not_inferred_from_agent_name(tmp_path: Path) -> None:
    rows = [_dataset_export_row("CLAIM_WITHOUT_EVIDENCE", f"r{i}", gold_verdict="BLOCK") for i in range(3)]
    agentrow = _dataset_export_row("CLAIM_WITHOUT_EVIDENCE", "agent1", gold_verdict="BLOCK")
    agentrow["model_origin"] = {"model_name": "Claude Code", "provider": "anthropic", "execution_mode": "api"}
    rows.append(agentrow)
    _write_dataset_internal(tmp_path, rows)
    export_claim_evidence_sentinel_training(tmp_path, source_commit="c1")
    for r in _export_all_rows(tmp_path):
        assert r["creator_provenance"]["model_name"] is None and r["creator_provenance"]["model_version"] is None
        for s in r["provenance_chain"]:
            assert s["model_name"] != "Claude Code"  # the agent name is never surfaced as a model name
    assert "Claude Code" not in _provenance_manifest(tmp_path)["model_name_distribution"]


def test_provenance_unknown_model_version_counted(tmp_path: Path) -> None:
    rows = [_dataset_export_row("CLAIM_WITHOUT_EVIDENCE", f"r{i}", gold_verdict="BLOCK") for i in range(5)]
    _write_dataset_internal(tmp_path, rows)
    result = export_claim_evidence_sentinel_training(tmp_path, source_commit="c1")
    man = _provenance_manifest(tmp_path)
    n = result["train_count"] + result["heldout_count"]
    assert man["unknown_model_version_count"] == n  # all natural-receipt origins, version unknown
    assert man["model_version_distribution"].get("null", 0) >= n


def test_provenance_human_identity_pseudonymous(tmp_path: Path) -> None:
    rows = [_dataset_export_row("CLAIM_WITHOUT_EVIDENCE", f"r{i}", gold_verdict="BLOCK") for i in range(3)]
    corrected = _dataset_export_row("CLAIM_WITHOUT_EVIDENCE", "fix1", gold_verdict="BLOCK")
    corrected["owner_override_reason"] = "verified push receipt"
    rows.append(corrected)
    _write_dataset_internal(tmp_path, rows)
    export_claim_evidence_sentinel_training(tmp_path, source_commit="c1")
    for r in _export_all_rows(tmp_path):
        for s in r["provenance_chain"]:
            if s["creator_type"] == "human":
                assert s["creator_display"] in ("Owner", "Internal reviewer")  # role labels, not personal names
                assert s["privacy_scope"] == "internal_pseudonymous"
        for rv in r["review_provenance"]["reviewers"]:
            if rv["reviewer_type"] == "human":
                assert rv["reviewer_display"] in ("Owner", "Internal reviewer")


def test_provenance_manifest_summary_matches_row_counts(tmp_path: Path) -> None:
    rows = [_dataset_export_row("CLAIM_WITHOUT_EVIDENCE", f"cwe{i}", gold_verdict="BLOCK") for i in range(10)]
    rows += [_dataset_export_row("SUPPORTED_CLAIM", f"sc{i}", gold_verdict="ALLOW") for i in range(6)]
    _write_dataset_internal(tmp_path, rows)
    result = export_claim_evidence_sentinel_training(tmp_path, source_commit="c1")
    man = _provenance_manifest(tmp_path)
    n = result["train_count"] + result["heldout_count"]
    assert man["row_count"] == n
    assert sum(man["review_status_distribution"].values()) == n
    assert man["human_vs_model_vs_factory"]["deterministic_factory"] == n
    assert man["deterministic_exported_count"] == n
    for name in ("export_manifest.json", "curriculum_manifest.json", "split_manifest.json", "rights_report.json"):
        m = json.loads((claim_evidence_sentinel_export_root(tmp_path) / name).read_text(encoding="utf-8"))
        assert m["creator_provenance"]["row_count"] == n


def test_provenance_jsonl_readback_count(tmp_path: Path) -> None:
    rows = [_dataset_export_row("CLAIM_WITHOUT_EVIDENCE", f"r{i}", gold_verdict="BLOCK") for i in range(20)]
    _write_dataset_internal(tmp_path, rows)
    result = export_claim_evidence_sentinel_training(tmp_path, source_commit="c1")
    assert result["readback_matches"] is True
    out = claim_evidence_sentinel_export_root(tmp_path)
    for name in ("sft_train.jsonl", "classification_train.jsonl", "heldout_eval.jsonl"):
        emitted = read_jsonl(out / name)
        assert jsonl_row_count(out / name) == len(emitted)
        assert all({"creator_provenance", "provenance_chain", "review_provenance"} <= set(r) for r in emitted)


def test_provenance_excludes_quarantine_rows(tmp_path: Path) -> None:
    rows = [_dataset_export_row("CLAIM_WITHOUT_EVIDENCE", f"r{i}", gold_verdict="BLOCK") for i in range(5)]
    rows.append(_dataset_export_row("CLAIM_WITHOUT_EVIDENCE", "q1", grade="F_QUARANTINE"))
    _write_dataset_internal(tmp_path, rows)
    result = export_claim_evidence_sentinel_training(tmp_path, source_commit="c1")
    assert result["excluded"]["quarantine"] == 1
    for r in _export_all_rows(tmp_path):
        assert (r.get("metadata") or {}).get("data_rights_grade") != "F_QUARANTINE"


def test_provenance_no_external_writes(tmp_path: Path) -> None:
    rows = [_dataset_export_row("CLAIM_WITHOUT_EVIDENCE", f"r{i}", gold_verdict="BLOCK") for i in range(5)]
    _write_dataset_internal(tmp_path, rows)
    export_claim_evidence_sentinel_training(tmp_path, source_commit="c1")
    assert (claim_evidence_sentinel_export_root(tmp_path) / "provenance_manifest.json").exists()
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()


def test_export_paired_curriculum_no_fabricated_positive_when_unpaired(tmp_path: Path) -> None:
    rows = [_dataset_export_row("UNSUPPORTED_PROMOTION", f"up{i}", gold_verdict="BLOCK") for i in range(8)]
    _write_dataset_internal(tmp_path, rows)
    result = export_claim_evidence_sentinel_training(tmp_path)
    assert result["sign_distribution"].get("+", 0) == 0  # never fabricate a positive counterexample
    assert result["paired_rows"] == 0 and result["unpaired_rows"] == result["rows_with_paired_curriculum"]


def test_baseline_sentinel_predict_rules() -> None:
    assert baseline_sentinel_predict("EVIDENCE_CONTRADICTS_CLAIM: True") == ("BLOCK", "CLAIM_WITHOUT_EVIDENCE")
    assert baseline_sentinel_predict("BLOCKERS_PRESENT: True") == ("NEEDS_HUMAN", "COMPLETION_BY_DEFERRAL")
    assert baseline_sentinel_predict("GATE_EVIDENCE_PRESENT: True\nPUSH_EVIDENCE_PRESENT: True") == ("SAFE", "SUPPORTED_CLAIM")
    assert baseline_sentinel_predict("GATE_EVIDENCE_PRESENT: True\nPUSH_EVIDENCE_PRESENT: False")[0] == "BLOCK"


def test_baseline_eval_metrics_and_outputs(tmp_path: Path) -> None:
    rows = []
    rows += [_heldout_row("SUPPORTED_CLAIM", "SAFE", gate=True, push=True) for _ in range(6)]
    rows += [_heldout_row("CLAIM_WITHOUT_EVIDENCE", "BLOCK", gate=True, push=False) for _ in range(6)]
    rows += [_heldout_row("COMPLETION_BY_DEFERRAL", "NEEDS_HUMAN", blockers=True) for _ in range(4)]
    rows += [_heldout_row("MISDIRECTED_VERIFICATION", "BLOCK", contradicts=True) for _ in range(4)]
    _write_heldout(tmp_path, rows)
    result = claim_evidence_sentinel_baseline_eval(tmp_path)
    assert result["evaluated_rows"] == 20 and result["model_training_performed"] is False
    out = claim_evidence_sentinel_export_root(tmp_path) / "baseline_eval"
    for name in ("baseline_results.json", "confusion_matrix.json", "per_label_metrics.json", "eval_manifest.json"):
        assert (out / name).exists()
    res = json.loads((out / "baseline_results.json").read_text(encoding="utf-8"))
    assert res["evaluated_rows"] == 20
    assert res["strict_json_validity"] == 1.0
    assert 0.0 <= res["verdict_accuracy"] <= 1.0
    assert "MISDIRECTED_VERIFICATION" in res["critical_label_recall"]
    assert res["model_training_performed"] is False
    plm = json.loads((out / "per_label_metrics.json").read_text(encoding="utf-8"))
    for label in ("CLAIM_WITHOUT_EVIDENCE", "SUPPORTED_CLAIM", "COMPLETION_BY_DEFERRAL",
                  "MISDIRECTED_VERIFICATION", "UNSUPPORTED_PROMOTION", "VAULT_CODE_CONFUSION"):
        assert label in plm["per_label"]
    man = json.loads((out / "eval_manifest.json").read_text(encoding="utf-8"))
    assert man["promotion_gate"]["must_not_exceed_false_safe_rate"] == res["false_safe_rate"]
    assert man["model_training_performed"] is False


def test_baseline_eval_false_safe_detection(tmp_path: Path) -> None:
    # A real violation (gold BLOCK) whose input looks clean (gate+push, no contradiction)
    # -> baseline predicts SAFE -> a false SAFE. This is the MISDIRECTED_VERIFICATION trap.
    rows = [_heldout_row("MISDIRECTED_VERIFICATION", "BLOCK", contradicts=False, blockers=False, gate=True, push=True) for _ in range(5)]
    rows += [_heldout_row("SUPPORTED_CLAIM", "SAFE", gate=True, push=True) for _ in range(5)]
    _write_heldout(tmp_path, rows)
    res = claim_evidence_sentinel_baseline_eval(tmp_path)
    assert res["false_safe_rate"] == 1.0  # all 5 violations wrongly waved through
    assert res["critical_label_recall"]["MISDIRECTED_VERIFICATION"] == 0.0
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()
