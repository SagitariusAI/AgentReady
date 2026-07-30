# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Shared cross-subsystem schema-version / identity constants for the Agent Data Foundry."""
from __future__ import annotations

# The first ClaimEvidence claim-evidence eval product. Identity is stable across the
# whole product line (default product_id for every ClaimEvidence emit/eval/release fn).
CLAIM_EVIDENCE_PRODUCT_ID = "claim_evidence-claim-evidence-eval-v0.1.0"

# Schema version stamped on every product-incident row and asserted on read by the
# mining / validation / gold-upgrade / eval paths. Changing this string is a
# schema migration, never an incidental edit.
CLAIM_EVIDENCE_SCHEMA_VERSION = "sf.product_incident.v0.2"

# The ClaimEvidence Sentinel training/eval label set -- the six on-target incident

# to these labels and the Sentinel eval enumerates per-label metrics over them, so
# the canonical tuple lives here and both import it (no import cycle).
SENTINEL_TRAINING_LABELS = (
    "CLAIM_WITHOUT_EVIDENCE", "COMPLETION_BY_DEFERRAL", "MISDIRECTED_VERIFICATION",
    "UNSUPPORTED_PROMOTION", "SUPPORTED_CLAIM", "VAULT_CODE_CONFUSION",
)

# Minimum per-label record counts the corpus must reach before the ClaimEvidence release

# writers, the eval-split coverage check, and the baseline-eval + release gates all read
# it, so the canonical requirement lives here and each subsystem imports it.
CLAIM_EVIDENCE_REQUIRED_LABELS = {
    "SUPPORTED_CLAIM": 100,
    "CLAIM_WITHOUT_EVIDENCE": 150,
    "COMPLETION_BY_DEFERRAL": 100,
    "UNSUPPORTED_PROMOTION": 50,
    "VAULT_CODE_CONFUSION": 50,
    "MISDIRECTED_VERIFICATION": 50,
}
