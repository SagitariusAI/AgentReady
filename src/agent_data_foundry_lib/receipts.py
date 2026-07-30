"""Shared receipt-domain primitives for the Agent Data Foundry.

The two things both the label-mining cluster and the receipt-export / build pipeline need from
the raw coordination receipts: `discover_receipts` (the dedup'd walk of every task-report JSON
under a coordination root) and `PROMOTABLE_POLICIES` (the work-product-policy allowlist that
gates whether a receipt may seed a SUPPORTED_CLAIM example). They are pure (stdlib + io_jsonl
read only), so both `mining.py` and the still-central build pipeline import them here instead of
one back-importing the other. Receipt discovery order, dedup-by-receipt-id behavior, and the
promotable policy set are preserved byte-for-byte.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_data_foundry_lib.io_jsonl import read_json

PROMOTABLE_POLICIES = {
    "company_owned_internal_reuse",
    "company_owned_review_before_training",
}


def discover_receipts(root: Path, coordination_root: Path | None = None) -> list[tuple[Path, dict[str, Any]]]:
    receipts: list[tuple[Path, dict[str, Any]]] = []
    seen: set[str] = set()
    receipt_root = coordination_root or root / "coordination"
    for path in sorted(receipt_root.glob("*/task-reports/*/*.json")):
        if path.name.lower() == "latest.json":
            continue
        payload = read_json(path)
        if not payload:
            continue
        receipt_id = str(payload.get("receipt_id") or path.stem)
        if receipt_id in seen:
            continue
        seen.add(receipt_id)
        receipts.append((path, payload))
    return receipts
