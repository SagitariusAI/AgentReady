# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from pathlib import Path

from agent_data_foundry_lib.gold_corpus import gold_jsonl_path
from agent_data_foundry_lib.mining import (
    append_mined_gold_rows,
    mine_supported_claims,
    mine_unsupported_promotions,
    receipt_claims_promotion,
    receipt_is_supported_claim_candidate,
    unsupported_promotion_missing_evidence,
    upgrade_claim_evidence_gold_schema,
)
from agent_data_foundry_lib.receipts import PROMOTABLE_POLICIES, discover_receipts


def _write_receipt(root: Path, repo: str, task: str, name: str, payload: dict) -> None:
    p = root / "coordination" / repo / "task-reports" / task / f"{name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload), encoding="utf-8")


def _strong_receipt(rid: str) -> dict:
    return {
        "receipt_id": rid, "repo": r"C:\Factory", "outcome": "shipped feature; gate green",
        "evidence": [{"path": "src/x.py"}], "quality": {"passed": True}, "promotion_blockers": [],
        "work_product_policy": "company_owned_internal_reuse",
    }


def test_promotable_policies_set():
    assert PROMOTABLE_POLICIES == {"company_owned_internal_reuse", "company_owned_review_before_training"}


def test_discover_receipts_dedups_by_receipt_id(tmp_path: Path):
    _write_receipt(tmp_path, "repoA", "t1", "r1", {"receipt_id": "dup"})
    _write_receipt(tmp_path, "repoA", "t1", "latest", {"receipt_id": "ignored"})  # latest.json skipped
    _write_receipt(tmp_path, "repoB", "t2", "r2", {"receipt_id": "dup"})  # same id -> deduped
    _write_receipt(tmp_path, "repoB", "t3", "r3", {"receipt_id": "unique"})
    found = discover_receipts(tmp_path)
    ids = sorted(str(r.get("receipt_id")) for _, r in found)
    assert ids == ["dup", "unique"]  # latest skipped, dup collapsed


def test_candidate_detectors():
    strong = _strong_receipt("s1")
    assert receipt_is_supported_claim_candidate(strong) is True
    weak = dict(strong, work_product_policy="external")  # not promotable
    assert receipt_is_supported_claim_candidate(weak) is False
    assert receipt_claims_promotion({"summary": "task complete and verified"}) is True
    assert receipt_claims_promotion({"summary": "in progress"}) is False
    miss = unsupported_promotion_missing_evidence({"promotion_blockers": ["b1"], "quality": {"passed": False}})
    assert "b1" in miss and "quality_gate_pass" in miss


def test_mine_supported_claims_writes_gold(tmp_path: Path):
    _write_receipt(tmp_path, "repoA", "t1", "r1", _strong_receipt("s1"))
    result = mine_supported_claims(tmp_path)
    assert result["label"] == "SUPPORTED_CLAIM" and result["mined"] == 1
    assert result["schema_version"] == "agentready.data_foundry.claim_evidence_label_mining.v1"
    rows = gold_jsonl_path(tmp_path).read_text(encoding="utf-8").strip().splitlines()
    assert len(rows) == 1 and json.loads(rows[0])["incident_type"] == "SUPPORTED_CLAIM"


def test_append_mined_gold_rows_dedups_against_existing_corpus(tmp_path: Path):
    first = append_mined_gold_rows(tmp_path, "L", [{"fingerprint": "fp1"}], "rep.json")
    assert first["mined"] == 1 and first["skipped_duplicates"] == 0
    # second batch: fp1 already in the corpus -> skipped; fp2 is new
    second = append_mined_gold_rows(tmp_path, "L", [{"fingerprint": "fp1"}, {"fingerprint": "fp2"}], "rep.json")
    assert second["candidates"] == 2 and second["mined"] == 1 and second["skipped_duplicates"] == 1


def test_mine_unsupported_promotions_and_upgrade_smoke(tmp_path: Path):
    bad = {"receipt_id": "u1", "summary": "promoted to done", "promotion_blockers": ["open"],
           "quality": {"passed": False}, "repo": r"C:\Factory"}
    _write_receipt(tmp_path, "repoA", "t1", "u1", bad)
    res = mine_unsupported_promotions(tmp_path)
    assert res["label"] == "UNSUPPORTED_PROMOTION" and res["mined"] == 1
    up = upgrade_claim_evidence_gold_schema(tmp_path)  # gold now has 1 current-schema row
    assert up["schema_version"] == "agentready.data_foundry.claim_evidence_gold_upgrade.v1"
    assert up["preserved_current_schema_rows"] >= 1


def test_reexported_identity():
    import agent_data_foundry as adf
    import agent_data_foundry_lib as adfl

    assert adf.mine_supported_claims is mine_supported_claims
    assert adf.upgrade_claim_evidence_gold_schema is upgrade_claim_evidence_gold_schema
    assert adf.discover_receipts is discover_receipts
    assert adfl.mine_vault_code_confusion.__module__ == "agent_data_foundry_lib.mining"
    assert adfl.PROMOTABLE_POLICIES is PROMOTABLE_POLICIES
