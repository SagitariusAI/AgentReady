# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from agent_data_foundry import (
    CLAIM_EVIDENCE_REQUIRED_LABELS,
    emit_dataset_card,
    emit_label_taxonomy,
    generate_supported_claim_controlled_cases,
    promote_controlled_cases,
)


def test_emit_label_taxonomy_declares_all_required_labels(tmp_path: Path) -> None:
    result = emit_label_taxonomy(tmp_path)

    taxonomy = json.loads((tmp_path / result["path"]).read_text(encoding="utf-8"))
    assert set(CLAIM_EVIDENCE_REQUIRED_LABELS).issubset(set(taxonomy["labels"]))
    assert all(taxonomy["labels"][label]["definition"] for label in CLAIM_EVIDENCE_REQUIRED_LABELS)
    assert all(taxonomy["labels"][label]["gold_verdict"] for label in CLAIM_EVIDENCE_REQUIRED_LABELS)
    assert taxonomy["labels"]["SUPPORTED_CLAIM"]["gold_verdict"] == "SAFE"


def test_emit_dataset_card_discloses_controlled_provenance(tmp_path: Path) -> None:
    generate_supported_claim_controlled_cases(tmp_path)
    promote_controlled_cases(tmp_path)

    result = emit_dataset_card(tmp_path)

    assert result["controlled_records"] == 20
    text = (tmp_path / result["path"]).read_text(encoding="utf-8")
    assert "## Provenance" in text
    assert "CONTROLLED_CASE" in text
    assert "SUPPORTED_CLAIM" in text
    assert "controlled SAFE subset" in text
