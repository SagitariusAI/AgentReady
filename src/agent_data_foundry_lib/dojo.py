"""Factory Dojo path/root helpers for the Agent Data Foundry.

Phase J1 of the module split (docs/refactors/AGENT_DATA_FOUNDRY_MODULE_SPLIT_PLAN.md):
the in-house Factory Dojo's root-path helper moved verbatim out of agent_data_foundry.py
with **no behavior change**. A pure leaf (imports only `pathlib`), so the training
exporter, the central Dojo builder, and the signal-coverage / safety / rights reports
can all share the canonical Dojo path with no import cycle.

Scope note: the Dojo gold-row builders (`receipt_gold_row`, `gold_coordination_row`)
and the receipt/task/defaults adjudication helpers they compose (`gold_output`,
`commercial_safety_flags`, `natural_provenance_fields`, `state_transition`,
`claim_evidence_alignment`, `task_verdict` / `task_evidence_profile`, the `receipt_*`
helpers) are NOT here: tool recon for Phase J1 showed that cluster is shared pervasively
with the controlled-case generators, mining, and harvest (all kept central per scope),
so it belongs to a future coordinated "adjudication" leaf, not this Dojo-path leaf.
"""
from __future__ import annotations

from pathlib import Path


def inhouse_dojo_root(root: Path) -> Path:
    return root / "data" / "training-library" / "30_curated" / "internal" / "factory-dojo"
