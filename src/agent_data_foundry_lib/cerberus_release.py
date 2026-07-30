"""Cerberus release gate + checksums + release receipt for the Agent Data Foundry.

The deterministic release-readiness authority for the Cerberus claim-evidence corpus:
``build_cerberus_release_gate`` runs every packaging gate (record count, label distribution,
schema validation, redaction/commercial-safety, dataset card, label taxonomy, eval split,
baseline eval, checksums) over the live Gold corpus and writes the gate report + sub-reports
into the release-ready scaffold; ``emit_cerberus_checksums`` seals every required artifact with a
sha256 manifest and writes the release receipt (mechanically release-ready vs founder/legal
sell-ready stay distinct). ``cerberus_checksums_gate`` validates the manifest, ``gate_item`` builds
each gate entry, and ``CERBERUS_RELEASE_ARTIFACTS`` lists the sealed set.

Clean leaf: composes the already-extracted gate providers (``cerberus_eval`` split + baseline
gates, ``dataset_card`` card + taxonomy gates), the Gold-corpus validator/schema writer
(``gold_corpus``), staged controlled rows (``controlled_cases``), ``io_jsonl``, the ``paths``
foundation, and ``schemas`` -- no back-import to agent_data_foundry. It writes under
``40_release_ready`` exactly as before; every gate verdict, report schema string, the sealed
artifact list, and the receipt fields are preserved byte-for-byte from the pre-split module.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_data_foundry_lib.cerberus_eval import (
    CERBERUS_EVAL_SPLIT_SEED,
    cerberus_baseline_eval_gate,
    cerberus_eval_split_gate,
)
from agent_data_foundry_lib.controlled_cases import staged_controlled_case_rows
from agent_data_foundry_lib.dataset_card import dataset_card_gate, label_taxonomy_gate
from agent_data_foundry_lib.gold_corpus import validate_cerberus_case, write_cerberus_schema
from agent_data_foundry_lib.io_jsonl import now_utc, read_json, read_jsonl, rel, sha256_file, write_json
from agent_data_foundry_lib.paths import AGENTREADY_HOME, cerberus_release_root, report_data_foundry_path
from agent_data_foundry_lib.schemas import CERBERUS_PRODUCT_ID, CERBERUS_REQUIRED_LABELS

CERBERUS_RELEASE_ARTIFACTS = [
    "dataset_card.md",
    "label_taxonomy.json",
    "data/eval_cases.jsonl",
    "data/expected_outputs.jsonl",
    "split_manifest.json",
    "reports/split_report.json",
    "reports/baseline_results.json",
    "reports/baseline_results.md",
]


def gate_item(passed: bool, message: str, details: Any = None) -> dict[str, Any]:
    item = {"passed": passed, "message": message}
    if details is not None:
        item["details"] = details
    return item


def cerberus_checksums_gate(release_root: Path) -> tuple[bool, str, Any]:
    sums_path = release_root / "checksums" / "sha256sums.txt"
    if not sums_path.exists():
        return (False, "Checksums not emitted; run emit-cerberus-checksums as the final packaging step.", None)
    recorded: dict[str, str] = {}
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = stripped.split("  ", 1)
        if len(parts) == 2:
            recorded[parts[1].strip()] = parts[0].strip()
    problems: dict[str, Any] = {}
    not_covered = [relpath for relpath in CERBERUS_RELEASE_ARTIFACTS if relpath not in recorded]
    if not_covered:
        problems["not_covered"] = not_covered
    stale_or_missing: list[str] = []
    for relpath in CERBERUS_RELEASE_ARTIFACTS:
        if relpath not in recorded:
            continue
        artifact = release_root / relpath
        if not artifact.exists():
            stale_or_missing.append(f"{relpath}:missing")
        elif sha256_file(artifact) != recorded[relpath]:
            stale_or_missing.append(f"{relpath}:hash_mismatch")
    if stale_or_missing:
        problems["stale_or_missing"] = stale_or_missing
    if problems:
        return (False, "Checksums incomplete or stale; re-run emit-cerberus-checksums after regenerating artifacts.", problems)
    return (True, "Checksums present and current for every required release artifact.", {"artifacts_sealed": len(CERBERUS_RELEASE_ARTIFACTS)})


def build_cerberus_release_gate(root: Path | str = AGENTREADY_HOME, product_id: str = CERBERUS_PRODUCT_ID) -> dict[str, Any]:
    root = Path(root)
    release_root = root / "data" / "training-library" / "40_release_ready" / product_id
    report_root = release_root / "reports"
    release_root.mkdir(parents=True, exist_ok=True)
    report_root.mkdir(parents=True, exist_ok=True)
    schema_path = write_cerberus_schema(root)

    gold_path = root / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    rows = read_jsonl(gold_path)
    label_distribution: dict[str, int] = {}
    schema_failures: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        label = str(row.get("incident_type") or "UNKNOWN")
        label_distribution[label] = label_distribution.get(label, 0) + 1
        failures = validate_cerberus_case(row)
        if failures:
            schema_failures.append({"row": index, "failures": failures})

    total_records = len(rows)
    natural_records = sum(1 for row in rows if row.get("provenance_type") in ("NATURAL_RECEIPT", None))
    controlled_records = sum(1 for row in rows if row.get("provenance_type") == "CONTROLLED_CASE")
    synthetic_records = sum(1 for row in rows if row.get("provenance_type") == "SYNTHETIC_VARIANT")
    human_authored_records = sum(1 for row in rows if row.get("human_authored") is True)
    staged_controlled_records = len(staged_controlled_case_rows(root))
    required_label_status = {
        label: {
            "required": required,
            "actual": label_distribution.get(label, 0),
            "passed": label_distribution.get(label, 0) >= required,
        }
        for label, required in CERBERUS_REQUIRED_LABELS.items()
    }
    commercial_safety_failures = [
        index
        for index, row in enumerate(rows, start=1)
        if not (row.get("commercial_safety") or {}).get("provider_neutral")
        or (row.get("commercial_safety") or {}).get("contains_raw_provider_output")
        or (row.get("commercial_safety") or {}).get("contains_secrets")
        or (row.get("commercial_safety") or {}).get("contains_internal_paths")
    ]

    _dataset_card_check = dataset_card_gate(release_root)
    _label_taxonomy_check = label_taxonomy_gate(release_root)
    _eval_split_check = cerberus_eval_split_gate(release_root)
    _baseline_eval_check = cerberus_baseline_eval_gate(release_root)
    _checksums_check = cerberus_checksums_gate(release_root)

    gate = {
        "product_identity": gate_item(product_id == CERBERUS_PRODUCT_ID, "Product identity is the first Cerberus claim-evidence eval."),
        "dataset_family_declared": gate_item(all(row.get("dataset_family") == "cerberus_sentinel" for row in rows) and bool(rows), "Every row declares the Cerberus dataset family."),
        "training_target_declared": gate_item(all(row.get("training_target") for row in rows) and bool(rows), "Every row declares a training target."),
        "minimum_record_count_met": gate_item(total_records >= 500, "At least 500 records are required for v0.1 release-ready packaging.", {"actual": total_records, "required": 500}),
        "label_distribution_acceptable": gate_item(all(item["passed"] for item in required_label_status.values()), "Required labels meet minimum counts.", required_label_status),
        "safe_examples_present": gate_item(label_distribution.get("SUPPORTED_CLAIM", 0) >= CERBERUS_REQUIRED_LABELS["SUPPORTED_CLAIM"], "At least 100 SAFE/SUPPORTED_CLAIM examples are required.", {"actual": label_distribution.get("SUPPORTED_CLAIM", 0), "required": CERBERUS_REQUIRED_LABELS["SUPPORTED_CLAIM"]}),
        "negative_only_corpus_blocked": gate_item(label_distribution.get("SUPPORTED_CLAIM", 0) > 0, "A Cerberus release must include supported-claim SAFE examples, not only violation examples.", {"actual_supported_claims": label_distribution.get("SUPPORTED_CLAIM", 0)}),
        "gold_outputs_present": gate_item(all(bool(row.get("gold_output")) for row in rows) and bool(rows), "Every row includes expected gold output."),
        "claim_evidence_alignment_present": gate_item(all(bool(row.get("claim_evidence_alignment")) for row in rows) and bool(rows), "Every row includes claim-evidence alignment."),
        "schema_validation_passed": gate_item(not schema_failures and bool(rows), "Every row matches the v0.2 claim-evidence schema.", schema_failures[:25]),
        "redaction_passed": gate_item(not commercial_safety_failures and bool(rows), "Commercial safety flags show no raw provider output, secrets, or internal paths."),
        "commercial_safety_passed": gate_item(not commercial_safety_failures and bool(rows), "Every row is provider-neutral and commercially safe by derived-record flags.", commercial_safety_failures[:25]),
        "train_validation_test_split_present": gate_item(*_eval_split_check),
        "dataset_card_present": gate_item(*_dataset_card_check),
        "label_taxonomy_present": gate_item(*_label_taxonomy_check),
        "baseline_eval_present": gate_item(*_baseline_eval_check),
        "checksums_present": gate_item(*_checksums_check),
    }
    status = "RELEASE_READY" if all(item["passed"] for item in gate.values()) else "NOT_RELEASE_READY"
    result = {
        "schema_version": "agentready.data_foundry.release_gate.v1",
        "generated_at": now_utc(),
        "product_id": product_id,
        "status": status,
        "dataset_readiness_level": "DRL-3",
        "target_drl": "DRL-5",
        "summary": {
            "total_records": total_records,
            "natural_records": natural_records,
            "controlled_records": controlled_records,
            "synthetic_records": synthetic_records,
            "human_authored_records": human_authored_records,
            "staged_controlled_records": staged_controlled_records,
            "source_gold_path": rel(root, gold_path) if gold_path.exists() else str(gold_path),
        },
        "label_distribution": label_distribution,
        "gate": gate,
        "schema_path": rel(root, schema_path),
    }
    write_json(release_root / "release_gate_report.json", result)
    write_json(report_root / "label_distribution.json", label_distribution)
    write_json(report_root / "schema_validation_report.json", {"passed": not schema_failures and bool(rows), "failures": schema_failures})
    write_json(report_root / "redaction_report.json", {"passed": not commercial_safety_failures and bool(rows), "commercial_safety_failures": commercial_safety_failures})
    (release_root / "README.md").write_text(
        "\n".join(
            [
                "# Cerberus Claim-Evidence Eval v0.1.0",
                "",
                f"Status: `{status}`",
                "",
                "This directory is a release-ready gate scaffold, not a commercial dataset package.",
                "Data may be emitted here only after record count, label distribution, schema, redaction, dataset card, baseline, split, and checksum gates pass.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return result


def emit_cerberus_checksums(root: Path | str = AGENTREADY_HOME, product_id: str = CERBERUS_PRODUCT_ID) -> dict[str, Any]:
    root = Path(root)
    release_root = cerberus_release_root(root, product_id)
    checksums_dir = release_root / "checksums"
    checksums_dir.mkdir(parents=True, exist_ok=True)

    entries: list[tuple[str, str]] = []
    missing: list[str] = []
    for relpath in CERBERUS_RELEASE_ARTIFACTS:
        artifact = release_root / relpath
        if not artifact.exists():
            missing.append(relpath)
            continue
        entries.append((sha256_file(artifact), relpath))
    sums_path = checksums_dir / "sha256sums.txt"
    sums_path.write_text("".join(f"{digest}  {relpath}\n" for digest, relpath in entries), encoding="utf-8")

    # Re-run the gate now that the checksums exist so the receipt reflects the
    # final, sealed status. The gate validates the checksums; it never calls back
    # into this emitter, so there is no recursion.
    gate = build_cerberus_release_gate(root, product_id)
    gate_items = gate.get("gate") or {}
    passed = sum(1 for item in gate_items.values() if item.get("passed"))
    summary = gate.get("summary") or {}
    split = read_json(release_root / "reports" / "split_report.json") or {}
    baseline_metrics = (read_json(release_root / "reports" / "baseline_results.json") or {}).get("metrics") or {}
    total = summary.get("total_records", 0)
    controlled = summary.get("controlled_records", 0)

    receipt = {
        "schema_version": "agentready.data_foundry.release_receipt.v1",
        "generated_at": now_utc(),
        "dataset_id": "cerberus-claim-evidence-eval",
        "version": "0.1.0",
        "product_id": product_id,
        "release_status": gate.get("status"),
        "record_count": total,
        "gate_passed": gate.get("status") == "RELEASE_READY",
        "gate_pass_count": f"{passed}/{len(gate_items)}",
        "provenance_breakdown": {
            "natural": summary.get("natural_records", 0),
            "controlled": controlled,
        },
        "controlled_ratio": round(controlled / total, 3) if total else 0.0,
        "heldout_count": split.get("heldout_count", 0),
        "split_seed": split.get("seed", CERBERUS_EVAL_SPLIT_SEED),
        "baseline_summary": {
            "verdict_accuracy_safe_vs_not_safe": baseline_metrics.get("verdict_accuracy"),
            "macro_f1": baseline_metrics.get("macro_f1"),
            "safe_false_positive_rate": baseline_metrics.get("SAFE_false_positive_rate"),
            "controlled_subset_accuracy": baseline_metrics.get("controlled_subset_accuracy"),
            "natural_subset_accuracy": baseline_metrics.get("natural_subset_accuracy"),
        },
        "checksums_path": rel(root, sums_path),
        "checksummed_artifacts": [relpath for _, relpath in entries],
        "missing_artifacts": missing,
        "commercial_clearance": "NOT_ATTORNEY_REVIEWED",
        "founder_release_required": True,
        "note": "Mechanically release-ready per the deterministic gate. Commercial sale still requires founder/legal clearance.",
    }
    receipt_path = release_root / "release_receipt.json"
    write_json(receipt_path, receipt)
    write_json(report_data_foundry_path(root, "cerberus-release-receipt-latest.json"), receipt)
    return {
        "checksummed": len(entries),
        "missing": missing,
        "release_status": gate.get("status"),
        "gate_pass_count": f"{passed}/{len(gate_items)}",
        "checksums_path": rel(root, sums_path),
        "receipt_path": rel(root, receipt_path),
    }
