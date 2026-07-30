# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from agent_data_foundry_lib.claim_evidence_eval import (
    CLAIM_EVIDENCE_EVAL_SPLIT_SEED,
    CLAIM_EVIDENCE_HELDOUT_FRACTION,
    baseline_predict,
    build_claim_evidence_eval_split,
    claim_evidence_baseline_eval,
    claim_evidence_baseline_eval_gate,
    claim_evidence_eval_split_gate,
)
from agent_data_foundry_lib.paths import claim_evidence_release_root


def test_split_seed_and_fraction_constants():
    assert CLAIM_EVIDENCE_EVAL_SPLIT_SEED == 424242
    assert 0.0 < CLAIM_EVIDENCE_HELDOUT_FRACTION < 1.0


def test_baseline_predict_returns_verdict_dict():
    # provider-neutral rule reading only input-side fields; returns a strict-JSON dict
    out = baseline_predict({
        "input_view": {"claim_type": "receipt_state_promotion"},
        "evidence_profile": {"gate_evidence_present": True, "push_evidence_present": True, "blockers_present": False},
    })
    assert isinstance(out, dict) and out.get("verdict") in {"SAFE", "BLOCK", "NEEDS_HUMAN"}


def test_gates_false_without_artifacts(tmp_path: Path):
    rr = claim_evidence_release_root(tmp_path)
    assert claim_evidence_eval_split_gate(rr)[0] is False  # no split emitted
    assert claim_evidence_baseline_eval_gate(rr)[0] is False  # no baseline eval emitted


def test_reexported_identity():
    import agent_data_foundry as adf
    import agent_data_foundry_lib as adfl

    assert adf.build_claim_evidence_eval_split is build_claim_evidence_eval_split
    assert adf.claim_evidence_baseline_eval is claim_evidence_baseline_eval
    assert adf.baseline_predict is baseline_predict
    assert adf.CLAIM_EVIDENCE_EVAL_SPLIT_SEED == CLAIM_EVIDENCE_EVAL_SPLIT_SEED
    assert adfl.claim_evidence_baseline_eval_gate is claim_evidence_baseline_eval_gate
