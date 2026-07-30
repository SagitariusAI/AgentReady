"""Shared cross-subsystem schema-version / identity constants for the Agent Data Foundry.

Phase B4a of the module split (docs/refactors/AGENT_DATA_FOUNDRY_MODULE_SPLIT_PLAN.md):
the *genuinely shared* pure constants — those referenced across multiple distinct
subsystems — moved here so the canonical identity lives in one place. Behavior is
unchanged: these are the exact same immutable strings, re-imported by
agent_data_foundry.py.

Scope is deliberately narrow to avoid a constants junk drawer. Only the Cerberus
product identity pair qualifies today: both bind many distinct subsystems —

- ``CERBERUS_PRODUCT_ID``  — the release-root / label-taxonomy / dataset-card /
  baseline-eval / checksums / release-gate functions (8 call sites).
- ``CERBERUS_SCHEMA_VERSION`` — the product-incident schema stamped and validated
  across incident mining, gold validation, and the gold-upgrade / eval paths (10
  call sites).

Domain-specific schema strings are intentionally NOT here — they belong to their
owning (future) leaf module, not a shared bucket:

- ``COORDINATION_HARVEST_SCHEMA`` / ``COORDINATION_ELIGIBLE_STATUSES`` — coordination
  harvest only.
- ``PRODUCT_STATE_LEDGER_SCHEMA_VERSION`` / ``PRODUCT_REALITY_BRIEF_POST_SCHEMA`` —
  product-state / reality-brief only.
- ``CODE_FITNESS_SCHEMA`` — code-fitness only.

Each stays in agent_data_foundry.py until its domain is extracted, so it travels
with its own behavior rather than being centralized prematurely.
"""
from __future__ import annotations

# The first Cerberus claim-evidence eval product. Identity is stable across the
# whole product line (default product_id for every Cerberus emit/eval/release fn).
CERBERUS_PRODUCT_ID = "cerberus-claim-evidence-eval-v0.1.0"

# Schema version stamped on every product-incident row and asserted on read by the
# mining / validation / gold-upgrade / eval paths. Changing this string is a
# schema migration, never an incidental edit.
CERBERUS_SCHEMA_VERSION = "sf.product_incident.v0.2"

# The Cerberus Sentinel training/eval label set -- the six on-target incident
# labels. Genuinely cross-subsystem (Phase H1): the training exporter filters rows
# to these labels and the Sentinel eval enumerates per-label metrics over them, so
# the canonical tuple lives here and both import it (no import cycle).
SENTINEL_TRAINING_LABELS = (
    "CLAIM_WITHOUT_EVIDENCE", "COMPLETION_BY_DEFERRAL", "MISDIRECTED_VERIFICATION",
    "UNSUPPORTED_PROMOTION", "SUPPORTED_CLAIM", "VAULT_CODE_CONFUSION",
)

# Minimum per-label record counts the corpus must reach before the Cerberus release
# gate will pass. Genuinely cross-subsystem (Phase Q): the label-taxonomy / dataset-card
# writers, the eval-split coverage check, and the baseline-eval + release gates all read
# it, so the canonical requirement lives here and each subsystem imports it.
CERBERUS_REQUIRED_LABELS = {
    "SUPPORTED_CLAIM": 100,
    "CLAIM_WITHOUT_EVIDENCE": 150,
    "COMPLETION_BY_DEFERRAL": 100,
    "UNSUPPORTED_PROMOTION": 50,
    "VAULT_CODE_CONFUSION": 50,
    "MISDIRECTED_VERIFICATION": 50,
}
