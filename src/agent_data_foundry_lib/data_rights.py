"""Data-rights eligibility gate for the Agent Data Foundry.

The dataset-level rights gate: ``data_rights_gate`` validates whether a dataset (the internal
Factory Dojo by default) is eligible for a declared intended use, tallying per-grade counts,
export / commercial-sale / quarantine / legal-review / founder-release rows, and per-row
pass/fail against the rights policy, then writes the gate report next to the dataset. It is a
pure validator — it never rebuilds a dataset, touches sealed Cerberus v0.1, writes under
``40_release_ready``, or infers clearance. ``DATASET_INTENDED_USES`` is the recognized intended-use
allowlist, consumed only by this gate.

Clean leaf: composes the row-level rights policy (``rights.data_rights_gate_row``), the Dojo path
(``dojo.inhouse_dojo_root``), ``io_jsonl``, and the ``paths`` home — no back-import to
agent_data_foundry. The gate report schema string, status logic, per-row reasons, and tallies are
preserved byte-for-byte from the pre-split module.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_data_foundry_lib.dojo import inhouse_dojo_root
from agent_data_foundry_lib.io_jsonl import as_dict, now_utc, read_jsonl, rel, write_json
from agent_data_foundry_lib.paths import AGENTREADY_HOME
from agent_data_foundry_lib.rights import data_rights_gate_row

DATASET_INTENDED_USES = [
    "internal_research",
    "internal_training",
    "external_eval",
    "external_training",
    "commercial_sale",
]


def data_rights_gate(
    root: Path | str = AGENTREADY_HOME,
    dataset_path: Path | str | None = None,
    intended_use: str = "internal_research",
) -> dict[str, Any]:
    """Validate whether a dataset is eligible for a declared intended use. Pure
    validator: it never rebuilds a dataset, touches Cerberus v0.1, writes to
    40_release_ready, or infers clearance."""
    root = Path(root)
    if dataset_path is None:
        dataset_path = inhouse_dojo_root(root) / "factory_dojo_internal.jsonl"
    dataset_path = Path(dataset_path)
    rows = read_jsonl(dataset_path)

    rows_passed = 0
    failures: list[dict[str, Any]] = []
    grade_counts: dict[str, int] = {}
    failure_reasons: dict[str, int] = {}
    export_allowed_rows = 0
    commercial_sale_rows = 0
    quarantine_rows = 0
    legal_review_required_rows = 0
    founder_release_required_rows = 0

    for index, row in enumerate(rows, start=1):
        rights = as_dict(row.get("data_rights"))
        grade = str(rights.get("grade"))
        grade_counts[grade] = grade_counts.get(grade, 0) + 1
        if rights.get("export_allowed"):
            export_allowed_rows += 1
        if rights.get("commercial_sale_allowed"):
            commercial_sale_rows += 1
        if grade == "F_QUARANTINE":
            quarantine_rows += 1
        if rights.get("requires_legal_review"):
            legal_review_required_rows += 1
        if rights.get("requires_founder_release"):
            founder_release_required_rows += 1
        passed, reason = data_rights_gate_row(row, intended_use)
        if passed:
            rows_passed += 1
        else:
            failure_reasons[reason] = failure_reasons.get(reason, 0) + 1
            if len(failures) < 25:
                failures.append({
                    "row_id": row.get("fingerprint") or row.get("source_id_hash") or index,
                    "reason": f"{reason} for {intended_use}",
                })

    rows_failed = len(rows) - rows_passed
    valid_use = intended_use in DATASET_INTENDED_USES
    status = "PASS" if (bool(rows) and rows_failed == 0 and valid_use) else "FAIL"
    try:
        dataset_rel = rel(root, dataset_path)
    except Exception:
        dataset_rel = str(dataset_path)
    report = {
        "schema_version": "sf.data_rights_gate.v0.1",
        "generated_at": now_utc(),
        "dataset_path": dataset_rel,
        "intended_use": intended_use,
        "intended_use_recognized": valid_use,
        "status": status,
        "rows_seen": len(rows),
        "rows_passed": rows_passed,
        "rows_failed": rows_failed,
        "grade_counts": grade_counts,
        "failure_reasons": failure_reasons,
        "failures": failures,
        "export_allowed_rows": export_allowed_rows,
        "commercial_sale_rows": commercial_sale_rows,
        "quarantine_rows": quarantine_rows,
        "legal_review_required_rows": legal_review_required_rows,
        "founder_release_required_rows": founder_release_required_rows,
    }
    report_path = dataset_path.parent / "data_rights_gate_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(report_path, report)
    return report
