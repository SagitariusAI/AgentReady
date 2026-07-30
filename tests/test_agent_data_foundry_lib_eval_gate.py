# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json

from agent_data_foundry_lib.eval_gate import (
    CRITICAL_SENTINEL_LABELS,
    STRICT_JSON_THRESHOLD,
    _coerce_prediction,
    _predicted_sign,
    baseline_sentinel_predict,
    claim_evidence_sentinel_baseline_eval,
    claim_evidence_sentinel_eval_and_gate,
    claim_evidence_sentinel_export_root,
)


def _heldout_row(rid, label, verdict, sign, *, grade="G5", anchors=None, pair_status="paired"):
    return {
        "input": "CLAIM: x\nEVIDENCE_CONTRADICTS_CLAIM: True",
        "label": label,
        "expected": {"verdict": verdict, "labels": [label], "evidence": [], "risk_score": 0, "required_action": ""},
        "paired_curriculum": {"sign": sign, "grade": grade, "pair_status": pair_status, "anchors": anchors or ["EVIDENCE"]},
        "metadata": {"source_id_hash": rid, "fingerprint": rid, "source_pool": "curated_dataset", "data_rights_grade": "C_EXTERNAL_EVAL_CANDIDATE"},
    }


def _write_heldout(root, rows):
    p = claim_evidence_sentinel_export_root(root) / "heldout_eval.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return p


def _write_baseline(root, **over):
    b = claim_evidence_sentinel_export_root(root) / "baseline_eval" / "baseline_results.json"
    b.parent.mkdir(parents=True, exist_ok=True)
    base = {"verdict_accuracy": 0.5, "label_macro_f1": 0.1, "false_safe_rate": 0.5,
            "critical_label_recall": {"MISDIRECTED_VERIFICATION": 0.0, "UNSUPPORTED_PROMOTION": 0.0}}
    base.update(over)
    b.write_text(json.dumps(base), encoding="utf-8")
    return b


def _write_preds(root, preds):
    p = root / "preds.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in preds) + "\n", encoding="utf-8")
    return p


def _pred(rid, verdict, label):
    return {"id": rid, "prediction": {"verdict": verdict, "labels": [label], "evidence": [], "risk_score": 0, "required_action": ""}}


def test_baseline_predict_rules():
    assert baseline_sentinel_predict("EVIDENCE_CONTRADICTS_CLAIM: True") == ("BLOCK", "CLAIM_WITHOUT_EVIDENCE")
    assert baseline_sentinel_predict("BLOCKERS_PRESENT: True") == ("NEEDS_HUMAN", "COMPLETION_BY_DEFERRAL")
    assert baseline_sentinel_predict("GATE_EVIDENCE_PRESENT: True\nPUSH_EVIDENCE_PRESENT: True") == ("SAFE", "SUPPORTED_CLAIM")
    assert baseline_sentinel_predict("GATE_EVIDENCE_PRESENT: True\nPUSH_EVIDENCE_PRESENT: False")[0] == "BLOCK"


def test_coerce_prediction_strict_json():
    assert _coerce_prediction({"verdict": "SAFE", "labels": [], "evidence": [], "risk_score": 0, "required_action": ""})[1] is True
    assert _coerce_prediction('{"verdict": "BLOCK", "labels": [], "evidence": [], "risk_score": 0, "required_action": ""}')[1] is True
    assert _coerce_prediction("not json {")[1] is False           # unparseable
    assert _coerce_prediction({"verdict": "MAYBE", "labels": [], "evidence": [], "risk_score": 0, "required_action": ""})[1] is False  # bad verdict
    assert _coerce_prediction({"verdict": "SAFE"})[1] is False     # missing schema keys


def test_predicted_sign_uses_label_map_then_verdict():
    assert _predicted_sign("SUPPORTED_CLAIM", None) == "+"   # from the PairedCurriculum label map
    assert _predicted_sign(None, "SAFE") == "+"              # verdict fallback
    assert _predicted_sign(None, "BLOCK") == "-"
    assert _predicted_sign(None, None) is None


def test_baseline_eval_metrics_and_outputs(tmp_path):
    rows = [_heldout_row("r1", "CLAIM_WITHOUT_EVIDENCE", "BLOCK", "-"),
            _heldout_row("r2", "SUPPORTED_CLAIM", "SAFE", "+")]
    _write_heldout(tmp_path, rows)
    result = claim_evidence_sentinel_baseline_eval(tmp_path)
    assert result["status"] == "EVALUATED" and result["model_training_performed"] is False
    out = claim_evidence_sentinel_export_root(tmp_path) / "baseline_eval"
    for name in ("baseline_results.json", "per_label_metrics.json", "confusion_matrix.json", "eval_manifest.json"):
        assert (out / name).exists(), name
    res = json.loads((out / "baseline_results.json").read_text(encoding="utf-8"))
    assert res["strict_json_validity"] == 1.0  # the deterministic baseline always emits valid JSON
    assert set(res["critical_label_recall"]) <= set(CRITICAL_SENTINEL_LABELS)
    assert res["model_training_performed"] is False
    # the manifest carries the promotion-gate yardstick
    man = json.loads((out / "eval_manifest.json").read_text(encoding="utf-8"))
    assert man["promotion_gate"]["must_keep_strict_json_validity_at"] == 1.0


def test_gate_baseline_required_without_baseline(tmp_path):
    _write_heldout(tmp_path, [_heldout_row("r1", "CLAIM_WITHOUT_EVIDENCE", "BLOCK", "-")])
    result = claim_evidence_sentinel_eval_and_gate(tmp_path, predictions_path=_write_preds(tmp_path, [_pred("r1", "BLOCK", "CLAIM_WITHOUT_EVIDENCE")]))
    assert result["decision"] == "BASELINE_REQUIRED" and result["promoted"] is False


def test_gate_perfect_predictions_promoted(tmp_path):
    rows = [_heldout_row("r1", "SUPPORTED_CLAIM", "SAFE", "+"),
            _heldout_row("r2", "CLAIM_WITHOUT_EVIDENCE", "BLOCK", "-")]
    _write_heldout(tmp_path, rows)
    _write_baseline(tmp_path)
    preds = [_pred("r1", "SAFE", "SUPPORTED_CLAIM"), _pred("r2", "BLOCK", "CLAIM_WITHOUT_EVIDENCE")]
    result = claim_evidence_sentinel_eval_and_gate(tmp_path, predictions_path=_write_preds(tmp_path, preds))
    assert result["verdict_accuracy"] == 1.0 and result["strict_json_validity"] == 1.0
    assert result["decision"] == "PROMOTED" and result["promoted"] is True
    # default NOT_PROMOTED safety: the decision/provenance record never claims training
    dec = json.loads((claim_evidence_sentinel_export_root(tmp_path) / "eval" / "promotion_decision.json").read_text(encoding="utf-8"))
    assert dec["training_loss_accepted_as_evidence"] is False and dec["model_training_performed"] is False
    # non-git tmp_path -> source_commit is an EXPLICIT None, never fabricated
    assert dec["creator_provenance"]["source_commit"] is None and dec["creator_provenance"]["creator_role"] == "evaluator"


def test_gate_baseline_equal_candidate_denied(tmp_path):
    # a candidate that merely TIES the baseline macro-F1 must not be promoted
    rows = [_heldout_row("r1", "CLAIM_WITHOUT_EVIDENCE", "BLOCK", "-")]
    _write_heldout(tmp_path, rows)
    _write_baseline(tmp_path, label_macro_f1=1.0, verdict_accuracy=0.0, false_safe_rate=1.0)
    preds = [_pred("r1", "BLOCK", "CLAIM_WITHOUT_EVIDENCE")]  # perfect -> macro_f1 ties at... below the inflated baseline
    result = claim_evidence_sentinel_eval_and_gate(tmp_path, predictions_path=_write_preds(tmp_path, preds))
    assert result["decision"] == "NOT_PROMOTED" and result["promoted"] is False
    dec = json.loads((claim_evidence_sentinel_export_root(tmp_path) / "eval" / "promotion_decision.json").read_text(encoding="utf-8"))
    assert any("label_macro_f1" in r for r in dec["reasons"])


def test_gate_false_safe_regression_denied(tmp_path):
    rows = [_heldout_row(f"r{i}", "MISDIRECTED_VERIFICATION", "BLOCK", "-", anchors=["TOOL_TARGET", "WORKFLOW"]) for i in range(4)]
    _write_heldout(tmp_path, rows)
    _write_baseline(tmp_path, false_safe_rate=0.0)
    preds = [_pred(f"r{i}", "SAFE", "SUPPORTED_CLAIM") for i in range(4)]  # waves everything through -> false SAFE
    result = claim_evidence_sentinel_eval_and_gate(tmp_path, predictions_path=_write_preds(tmp_path, preds))
    assert result["false_safe_rate"] == 1.0 and result["decision"] == "NOT_PROMOTED"
    dec = json.loads((claim_evidence_sentinel_export_root(tmp_path) / "eval" / "promotion_decision.json").read_text(encoding="utf-8"))
    assert any("false_safe" in r for r in dec["reasons"])


def test_gate_emits_all_output_files(tmp_path):
    _write_heldout(tmp_path, [_heldout_row("r1", "CLAIM_WITHOUT_EVIDENCE", "BLOCK", "-")])
    _write_baseline(tmp_path)
    claim_evidence_sentinel_eval_and_gate(tmp_path, predictions_path=_write_preds(tmp_path, [_pred("r1", "BLOCK", "CLAIM_WITHOUT_EVIDENCE")]))
    out = claim_evidence_sentinel_export_root(tmp_path) / "eval"
    for name in ("eval_results.json", "promotion_decision.json", "confusion_matrix.json",
                 "per_label_metrics.json", "paired_curriculum_metrics.json", "eval_manifest.json"):
        assert (out / name).exists(), name
    assert STRICT_JSON_THRESHOLD == 0.99
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()


def test_reexported_identity_from_agent_data_foundry():
    import agent_data_foundry as adf

    assert adf.claim_evidence_sentinel_eval_and_gate is claim_evidence_sentinel_eval_and_gate
    assert adf.claim_evidence_sentinel_baseline_eval is claim_evidence_sentinel_baseline_eval
    assert adf.claim_evidence_sentinel_export_root is claim_evidence_sentinel_export_root
    assert adf.baseline_sentinel_predict is baseline_sentinel_predict
    # SENTINEL_TRAINING_LABELS now lives in schemas and is re-exported by both
    assert adf.SENTINEL_TRAINING_LABELS == ("CLAIM_WITHOUT_EVIDENCE", "COMPLETION_BY_DEFERRAL",
                                            "MISDIRECTED_VERIFICATION", "UNSUPPORTED_PROMOTION",
                                            "SUPPORTED_CLAIM", "VAULT_CODE_CONFUSION")
