# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from agent_data_foundry_lib.dataset_card import (
    CLAIM_EVIDENCE_LABEL_TAXONOMY,
    corpus_provenance_breakdown,
    dataset_card_gate,
    emit_dataset_card,
    emit_label_taxonomy,
    label_taxonomy_gate,
)
from agent_data_foundry_lib.gold_corpus import gold_jsonl_path
from agent_data_foundry_lib.io_jsonl import append_jsonl
from agent_data_foundry_lib.paths import claim_evidence_release_root
from agent_data_foundry_lib.schemas import CLAIM_EVIDENCE_REQUIRED_LABELS


def _seed_gold(root: Path) -> None:
    append_jsonl(gold_jsonl_path(root), [
        {"incident_type": "SUPPORTED_CLAIM", "provenance_type": "NATURAL_RECEIPT"},
        {"incident_type": "SUPPORTED_CLAIM", "provenance_type": "CONTROLLED_CASE", "controlled_case_family": "SUPPORTED_CLAIM"},
        {"incident_type": "VAULT_CODE_CONFUSION", "provenance_type": "CONTROLLED_CASE", "controlled_case_family": "VAULT_CODE_CONFUSION"},
    ])


def test_label_taxonomy_definitions_stable():
    assert set(CLAIM_EVIDENCE_LABEL_TAXONOMY) == set(CLAIM_EVIDENCE_REQUIRED_LABELS)
    assert CLAIM_EVIDENCE_LABEL_TAXONOMY["SUPPORTED_CLAIM"]["gold_verdict"] == "SAFE"
    assert all(CLAIM_EVIDENCE_LABEL_TAXONOMY[lbl]["gold_verdict"] == "BLOCK" for lbl in CLAIM_EVIDENCE_LABEL_TAXONOMY if lbl != "SUPPORTED_CLAIM")


def test_corpus_provenance_breakdown_counts():
    rows = [
        {"incident_type": "SUPPORTED_CLAIM", "provenance_type": "NATURAL_RECEIPT"},
        {"incident_type": "SUPPORTED_CLAIM", "provenance_type": "CONTROLLED_CASE", "controlled_case_family": "SUPPORTED_CLAIM"},
        {"incident_type": "VAULT_CODE_CONFUSION"},  # None provenance -> natural
    ]
    b = corpus_provenance_breakdown(rows)
    assert b["by_label"]["SUPPORTED_CLAIM"] == {"natural": 1, "controlled": 1, "other": 0, "total": 2}
    assert b["by_label"]["VAULT_CODE_CONFUSION"]["natural"] == 1
    assert b["by_controlled_family"] == {"SUPPORTED_CLAIM": 1}


def test_emit_label_taxonomy_writes_required_minimums(tmp_path: Path):
    result = emit_label_taxonomy(tmp_path)
    payload = json.loads((claim_evidence_release_root(tmp_path) / "label_taxonomy.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "agentready.data_foundry.label_taxonomy.v1"
    assert payload["required_minimums"] == CLAIM_EVIDENCE_REQUIRED_LABELS
    assert set(payload["labels"]) == set(CLAIM_EVIDENCE_LABEL_TAXONOMY)
    assert result["labels"] == list(CLAIM_EVIDENCE_LABEL_TAXONOMY)


def test_emit_dataset_card_discloses_provenance(tmp_path: Path):
    _seed_gold(tmp_path)
    report = emit_dataset_card(tmp_path)
    assert report["schema_version"] == "agentready.data_foundry.dataset_card.v1"
    assert report["total_records"] == 3 and report["natural_records"] == 1 and report["controlled_records"] == 2
    card = (claim_evidence_release_root(tmp_path) / "dataset_card.md").read_text(encoding="utf-8")
    for marker in ("## Provenance", "CONTROLLED_CASE", "SUPPORTED_CLAIM", "Natural"):
        assert marker in card


def test_gates_require_emitted_artifacts(tmp_path: Path):
    rr = claim_evidence_release_root(tmp_path)
    assert dataset_card_gate(rr)[0] is False  # not emitted
    assert label_taxonomy_gate(rr)[0] is False
    _seed_gold(tmp_path)
    emit_label_taxonomy(tmp_path)
    emit_dataset_card(tmp_path)
    assert dataset_card_gate(rr)[0] is True
    assert label_taxonomy_gate(rr)[0] is True


def test_reexported_identity():
    import agent_data_foundry as adf
    import agent_data_foundry_lib as adfl

    assert adf.emit_dataset_card is emit_dataset_card
    assert adf.emit_label_taxonomy is emit_label_taxonomy
    assert adf.dataset_card_gate is dataset_card_gate
    assert adf.label_taxonomy_gate is label_taxonomy_gate
    assert adfl.CLAIM_EVIDENCE_LABEL_TAXONOMY is CLAIM_EVIDENCE_LABEL_TAXONOMY
    assert adf.CLAIM_EVIDENCE_REQUIRED_LABELS is CLAIM_EVIDENCE_REQUIRED_LABELS  # now from schemas, re-imported centrally
