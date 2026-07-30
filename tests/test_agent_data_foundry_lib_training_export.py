# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json

from agent_data_foundry_lib.eval_gate import claim_evidence_sentinel_export_root
from agent_data_foundry_lib.training_export import (
    SENTINEL_SYSTEM_PROMPT,
    _sentinel_heldout,
    _sentinel_input_text,
    _sentinel_target,
    _sentinel_verdict,
    export_claim_evidence_sentinel_training,
)

# The exporter reads the Curated Dataset via the central (lazy-imported) curated_dataset_root.
_DATASET_REL = "data/training-library/30_curated/internal/factory-dataset/curated_dataset_internal.jsonl"

# Multiple rows per label plus one quarantine row exercise both deterministic
# split sides while proving quarantine is dropped.
_LABELS = ("CLAIM_WITHOUT_EVIDENCE", "COMPLETION_BY_DEFERRAL", "MISDIRECTED_VERIFICATION",
           "UNSUPPORTED_PROMOTION", "SUPPORTED_CLAIM", "VAULT_CODE_CONFUSION")


def _dataset_row(rid, label, *, grade="C_EXTERNAL_EVAL_CANDIDATE", verdict="BLOCK"):
    return {
        "schema_version": "sf.product_incident.v0.2",
        "incident_type": label,
        "source_id_hash": rid,
        "fingerprint": rid,
        "verdict": verdict,
        "abstracted_agent_claim": "A factory agent made a software delivery claim.",
        "input_view": {"claim": "claim", "claim_type": "delivery", "task_status": "done", "evidence_count": 1},
        "evidence_profile": {"evidence_count": 1, "gate_evidence_present": True, "push_evidence_present": True, "blockers_present": False},
        "claim_evidence_alignment": {"evidence_contradicts_claim": verdict == "BLOCK", "evidence_required": ["gate"]},
        "gold_output": {"verdict": "BLOCK" if verdict == "BLOCK" else "ALLOW", "required_action": "fix"},
        "data_rights": {"grade": grade, "export_allowed": False, "commercial_sale_allowed": False},
        "provenance_type": "NATURAL_RECEIPT",
        "source_model_output_used": False,
    }


def _seed_dataset(root, rows):
    p = root / _DATASET_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _full_corpus():
    # Eight stable keys per label cover both sides of the deterministic 50% split.
    rows = []
    for label in _LABELS:
        for i in range(8):
            rows.append(_dataset_row(f"{label}-{i}", label, verdict="BLOCK" if label != "SUPPORTED_CLAIM" else "SAFE"))
    rows.append(_dataset_row("quarantined-1", "CLAIM_WITHOUT_EVIDENCE", grade="F_QUARANTINE"))
    return rows


def test_export_outputs_and_invariants(tmp_path):
    _seed_dataset(tmp_path, _full_corpus())
    result = export_claim_evidence_sentinel_training(tmp_path, heldout_pct=50, source_commit="c1")
    out = claim_evidence_sentinel_export_root(tmp_path)
    for name in ("sft_train.jsonl", "classification_train.jsonl", "heldout_eval.jsonl",
                 "export_manifest.json", "rights_report.json", "split_manifest.json",
                 "curriculum_manifest.json", "provenance_manifest.json"):
        assert (out / name).exists(), name
    assert result["status"] == "CURATED_READY"
    assert result["broad_label_readiness"] is True
    assert not result["unsupported_labels"]
    assert not result["heldout_unsupported_labels"]
    assert result["model_training_performed"] is False
    assert result["readback_matches"] is True       # JSONL readback == emitted
    assert result["train_heldout_no_overlap"] is True
    assert result["all_restricted_use"] is True
    assert result["source_commit"] == "c1"
    assert result["excluded"]["quarantine"] == 1     # F_QUARANTINE dropped


def test_no_train_heldout_overlap_and_all_labels(tmp_path):
    _seed_dataset(tmp_path, _full_corpus())
    export_claim_evidence_sentinel_training(tmp_path, heldout_pct=50, source_commit="c1")
    out = claim_evidence_sentinel_export_root(tmp_path)
    sft = [json.loads(r) for r in (out / "sft_train.jsonl").read_text(encoding="utf-8").splitlines() if r.strip()]
    held = [json.loads(r) for r in (out / "heldout_eval.jsonl").read_text(encoding="utf-8").splitlines() if r.strip()]
    train_ids = {r["metadata"]["source_id_hash"] for r in sft}
    held_ids = {r["metadata"]["source_id_hash"] for r in held}
    assert train_ids.isdisjoint(held_ids)            # deterministic, no overlap
    # every on-target label represented across the union of splits
    seen = {r["metadata"]["incident_type"] for r in sft} | {r["label"] for r in held}
    assert seen == set(_LABELS)


def test_split_is_deterministic(tmp_path):
    # Two independent roots seeded with the same corpus must yield the same split
    # (the key-stable sha256 hash assigns each source id to a fixed side).
    corpus = _full_corpus()
    a, b = tmp_path / "a", tmp_path / "b"
    _seed_dataset(a, corpus)
    _seed_dataset(b, corpus)
    r1 = export_claim_evidence_sentinel_training(a, heldout_pct=25, source_commit="c1")
    r2 = export_claim_evidence_sentinel_training(b, heldout_pct=25, source_commit="c1")
    assert r1["train_count"] == r2["train_count"] and r1["heldout_count"] == r2["heldout_count"]
    ha = (claim_evidence_sentinel_export_root(a) / "sft_train.jsonl").read_text(encoding="utf-8")
    hb = (claim_evidence_sentinel_export_root(b) / "sft_train.jsonl").read_text(encoding="utf-8")
    assert ha == hb  # byte-identical training set from identical input


def test_sft_format_strict_sentinel_json(tmp_path):
    _seed_dataset(tmp_path, _full_corpus())
    export_claim_evidence_sentinel_training(tmp_path, heldout_pct=0, source_commit="c1")  # all -> train
    out = claim_evidence_sentinel_export_root(tmp_path)
    sft = [json.loads(r) for r in (out / "sft_train.jsonl").read_text(encoding="utf-8").splitlines() if r.strip()]
    row = sft[0]
    assert [m["role"] for m in row["messages"]] == ["system", "user", "assistant"]
    assert row["messages"][0]["content"] == SENTINEL_SYSTEM_PROMPT
    target = json.loads(row["messages"][2]["content"])  # assistant emits strict JSON
    assert set(target) == {"verdict", "labels", "evidence", "risk_score", "required_action"}
    assert "paired_curriculum" in row and "creator_provenance" in row  # curriculum + provenance present


def test_eval_gate_compatibility_heldout_ids(tmp_path):
    # heldout IDs must remain stable so the eval gate can match predictions by id
    _seed_dataset(tmp_path, _full_corpus())
    export_claim_evidence_sentinel_training(tmp_path, heldout_pct=100, source_commit="c1")  # all -> heldout
    from agent_data_foundry_lib.eval_gate import (
        claim_evidence_sentinel_baseline_eval,
        claim_evidence_sentinel_eval_and_gate,
    )
    base = claim_evidence_sentinel_baseline_eval(tmp_path)
    assert base["status"] == "EVALUATED" and base["evaluated_rows"] > 0
    out = claim_evidence_sentinel_export_root(tmp_path)
    held = [json.loads(r) for r in (out / "heldout_eval.jsonl").read_text(encoding="utf-8").splitlines() if r.strip()]
    rid = held[0]["metadata"]["source_id_hash"]
    preds = [{"id": rid, "prediction": {"verdict": "BLOCK", "labels": [held[0]["label"]], "evidence": [], "risk_score": 0, "required_action": ""}}]
    pp = tmp_path / "preds.jsonl"
    pp.write_text("\n".join(json.dumps(p) for p in preds) + "\n", encoding="utf-8")
    gate = claim_evidence_sentinel_eval_and_gate(tmp_path, predictions_path=pp)
    assert gate["matched_predictions"] >= 1  # the heldout id matched a prediction


def test_helpers_and_no_release_ready(tmp_path):
    assert _sentinel_verdict({"verdict": "SAFE"}) == "SAFE"
    assert _sentinel_verdict({"gold_output": {"verdict": "BLOCK"}}) == "BLOCK"
    assert _sentinel_target({"incident_type": "X"}, "BLOCK")["risk_score"] == 90
    assert "CLAIM:" in _sentinel_input_text({"abstracted_agent_claim": "did x"})
    # key-stable: same key -> same side
    assert _sentinel_heldout("k", 100) is True and _sentinel_heldout("k", 0) is False
    _seed_dataset(tmp_path, _full_corpus())
    export_claim_evidence_sentinel_training(tmp_path, source_commit="c1")
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()


def test_reexported_identity_from_agent_data_foundry():
    import agent_data_foundry as adf

    assert adf.export_claim_evidence_sentinel_training is export_claim_evidence_sentinel_training
