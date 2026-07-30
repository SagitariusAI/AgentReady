# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import agent_data_foundry_lib as adf_lib
from agent_data_foundry_lib.schemas import (
    CLAIM_EVIDENCE_PRODUCT_ID,
    CLAIM_EVIDENCE_SCHEMA_VERSION,
)


def test_schema_strings_are_exact_and_unchanged() -> None:
    # These strings are a public contract: stamped on artifacts and asserted on
    # read. A change here is a schema migration, so pin the exact values.
    assert CLAIM_EVIDENCE_PRODUCT_ID == "claim_evidence-claim-evidence-eval-v0.1.0"
    assert CLAIM_EVIDENCE_SCHEMA_VERSION == "sf.product_incident.v0.2"


def test_reexported_identity_from_agent_data_foundry() -> None:
    import agent_data_foundry as adf

    assert adf.CLAIM_EVIDENCE_PRODUCT_ID is CLAIM_EVIDENCE_PRODUCT_ID
    assert adf.CLAIM_EVIDENCE_SCHEMA_VERSION is CLAIM_EVIDENCE_SCHEMA_VERSION


def test_exposed_at_package_level() -> None:
    assert adf_lib.CLAIM_EVIDENCE_PRODUCT_ID is CLAIM_EVIDENCE_PRODUCT_ID
    assert adf_lib.CLAIM_EVIDENCE_SCHEMA_VERSION is CLAIM_EVIDENCE_SCHEMA_VERSION
    assert "CLAIM_EVIDENCE_PRODUCT_ID" in adf_lib.__all__
    assert "CLAIM_EVIDENCE_SCHEMA_VERSION" in adf_lib.__all__


def test_emitted_artifacts_still_stamp_the_constants(tmp_path) -> None:
    # Behavioral guard: the re-imported constants must flow through real emitters.
    import agent_data_foundry as adf

    # A built gold row stamps the product-incident schema version.
    receipt = {
        "receipt_id": "r1", "repo": r"C:\Factory",
        "paths_touched": ["src/x.py", "tests/test_x.py"],
        "commands_run": ["pytest tests/test_x.py"],
        "evidence": [{"path": "src/x.py", "status": "pass"}],
        "quality": {"passed": True}, "outcome": "done",
    }
    row = adf.receipt_gold_row(receipt, "SUPPORTED_CLAIM", "SAFE", "ok")
    assert row["schema_version"] == CLAIM_EVIDENCE_SCHEMA_VERSION == "sf.product_incident.v0.2"

    # The dataset card stamps the product id.
    card = adf.emit_dataset_card(tmp_path)
    assert card["product_id"] == CLAIM_EVIDENCE_PRODUCT_ID == "claim_evidence-claim-evidence-eval-v0.1.0"
