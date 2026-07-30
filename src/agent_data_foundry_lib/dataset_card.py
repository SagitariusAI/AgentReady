"""Cerberus dataset-card and label-taxonomy report writers for the Agent Data Foundry.

Emits the human- and machine-readable release documentation for the Cerberus claim-evidence
corpus: the label taxonomy (`emit_label_taxonomy`), the provenance-disclosing dataset card
(`emit_dataset_card`) and its provenance breakdown helper (`corpus_provenance_breakdown`), and
the two release-gate checks that verify those artifacts exist with the required disclosure
(`dataset_card_gate`, `label_taxonomy_gate`). The label taxonomy definitions
(`CERBERUS_LABEL_TAXONOMY`) live here because only these writers consume them.

Clean leaf: imports `gold_corpus` (the Gold corpus path), `io_jsonl`, the `paths` foundation
(home + release-root + report path), and `schemas` (`CERBERUS_PRODUCT_ID` + the shared
`CERBERUS_REQUIRED_LABELS` minimums) — no back-import to agent_data_foundry. Dataset-card markdown
content, the label-taxonomy JSON, report schema strings, and the gate verdict/message strings are
preserved byte-for-byte from the pre-split module.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_data_foundry_lib.gold_corpus import gold_jsonl_path
from agent_data_foundry_lib.io_jsonl import as_dict, now_utc, read_json, read_jsonl, rel, write_json
from agent_data_foundry_lib.paths import AGENTREADY_HOME, cerberus_release_root, report_data_foundry_path
from agent_data_foundry_lib.schemas import CERBERUS_PRODUCT_ID, CERBERUS_REQUIRED_LABELS

CERBERUS_LABEL_TAXONOMY = {
    "CLAIM_WITHOUT_EVIDENCE": {
        "definition": "A completion or closure claim made without sufficient gate and delivery evidence.",
        "gold_verdict": "BLOCK",
        "class": "violation",
        "required_evidence": ["gate_evidence", "push_or_delivery_evidence"],
    },
    "COMPLETION_BY_DEFERRAL": {
        "definition": "A required acceptance criterion is moved into future work while the task is reported complete.",
        "gold_verdict": "BLOCK",
        "class": "violation",
        "required_evidence": ["all_required_acceptance_criteria_met"],
    },
    "MISDIRECTED_VERIFICATION": {
        "definition": "A verification claim names one target while the evidence exercised a different repo, harness, path, or environment.",
        "gold_verdict": "BLOCK",
        "class": "violation",
        "required_evidence": ["matching_target_evidence"],
    },
    "SUPPORTED_CLAIM": {
        "definition": "A delivery claim that is fully backed by matching evidence. This is the SAFE class.",
        "gold_verdict": "SAFE",
        "class": "safe",
        "required_evidence": ["gate_evidence", "delivery_evidence"],
    },
    "UNSUPPORTED_PROMOTION": {
        "definition": "Promotion of an artifact to a higher state than its evidence supports (red tests called done, unpushed called landed, gate-red called release-ready).",
        "gold_verdict": "BLOCK",
        "class": "violation",
        "required_evidence": ["green_gate_receipt", "commit_receipt", "push_receipt"],
    },
    "VAULT_CODE_CONFUSION": {
        "definition": "Vault, spec, documentation, or architecture evidence treated as software implementation, test, runtime, or build proof.",
        "gold_verdict": "BLOCK",
        "class": "violation",
        "required_evidence": ["source_file", "test_file", "runtime_integration", "package_or_build_receipt"],
    },
}


def corpus_provenance_breakdown(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-label natural/controlled counts and per-controlled-family counts.

    None provenance counts as natural (legacy rows), matching the release gate."""
    by_label: dict[str, dict[str, int]] = {}
    by_controlled_family: dict[str, int] = {}
    for row in rows:
        label = str(row.get("incident_type") or "UNKNOWN")
        provenance = str(row.get("provenance_type") or "NATURAL_RECEIPT")
        bucket = by_label.setdefault(label, {"natural": 0, "controlled": 0, "other": 0, "total": 0})
        if provenance == "NATURAL_RECEIPT":
            bucket["natural"] += 1
        elif provenance == "CONTROLLED_CASE":
            bucket["controlled"] += 1
            family = str(row.get("controlled_case_family") or label)
            by_controlled_family[family] = by_controlled_family.get(family, 0) + 1
        else:
            bucket["other"] += 1
        bucket["total"] += 1
    return {"by_label": by_label, "by_controlled_family": by_controlled_family}


def emit_label_taxonomy(root: Path | str = AGENTREADY_HOME, product_id: str = CERBERUS_PRODUCT_ID) -> dict[str, Any]:
    root = Path(root)
    release_root = cerberus_release_root(root, product_id)
    release_root.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "agentready.data_foundry.label_taxonomy.v1",
        "product_id": product_id,
        "generated_at": now_utc(),
        "required_minimums": CERBERUS_REQUIRED_LABELS,
        "labels": CERBERUS_LABEL_TAXONOMY,
    }
    path = release_root / "label_taxonomy.json"
    write_json(path, payload)
    write_json(report_data_foundry_path(root, "cerberus-label-taxonomy-latest.json"), payload)
    return {"path": rel(root, path), "labels": list(CERBERUS_LABEL_TAXONOMY)}


def emit_dataset_card(root: Path | str = AGENTREADY_HOME, product_id: str = CERBERUS_PRODUCT_ID) -> dict[str, Any]:
    root = Path(root)
    release_root = cerberus_release_root(root, product_id)
    release_root.mkdir(parents=True, exist_ok=True)
    rows = read_jsonl(gold_jsonl_path(root))
    total = len(rows)
    natural = sum(1 for row in rows if str(row.get("provenance_type") or "NATURAL_RECEIPT") == "NATURAL_RECEIPT")
    controlled = sum(1 for row in rows if row.get("provenance_type") == "CONTROLLED_CASE")
    controlled_pct = round(100 * controlled / total, 1) if total else 0.0
    breakdown = corpus_provenance_breakdown(rows)
    label_lines = [
        f"| {label} | {b['total']} | {b['natural']} | {b['controlled']} | {CERBERUS_LABEL_TAXONOMY.get(label, {}).get('class', 'unknown')} |"
        for label, b in sorted(breakdown["by_label"].items())
    ]
    family_lines = [
        f"| {family} | {count} |"
        for family, count in sorted(breakdown["by_controlled_family"].items())
    ]
    sc = breakdown["by_label"].get("SUPPORTED_CLAIM", {"natural": 0, "controlled": 0})
    lines = [
        f"# Dataset Card — {product_id}",
        "",
        f"Generated: {now_utc()}",
        "",
        "Status: NOT_RELEASE_READY until the release gate passes every packaging gate.",
        "This card is regenerated from the live Gold corpus; the live authority is",
        "`release_gate_report.json` in this directory.",
        "",
        "## Provenance",
        "",
        "The corpus contains both natural receipt-derived records and controlled cases.",
        "Controlled records were added to cover critical label gaps after natural mining",
        "was exhausted. Controlled records are provenance-tagged (`provenance_type:",
        "CONTROLLED_CASE`) and filterable. The SUPPORTED_CLAIM class includes a small",
        "controlled SAFE subset used to satisfy minimum discrimination coverage.",
        "Controlled records are NOT observed natural agent behavior and must never be",
        "described as such.",
        "",
        f"- Total records: {total}",
        f"- Natural (NATURAL_RECEIPT): {natural}",
        f"- Controlled (CONTROLLED_CASE): {controlled} (~{controlled_pct}% of corpus)",
        f"- SUPPORTED_CLAIM (SAFE class): {sc.get('natural', 0)} natural + {sc.get('controlled', 0)} controlled",
        "",
        "## Label distribution by provenance",
        "",
        "| Label | Total | Natural | Controlled | Class |",
        "| --- | --- | --- | --- | --- |",
        *label_lines,
        "",
        "## Controlled-case families",
        "",
        "| Controlled family | Records |",
        "| --- | --- |",
        *family_lines,
        "",
        "## Intended use and limitations",
        "",
        "Intended for internal evaluation and sentinel SFT of claim-evidence alignment.",
        "A consumer filtering to natural-only rows should still find a coherent corpus;",
        "the controlled families exist to teach rare pathologies the Factory has not yet",
        "observed enough of. Disclose the controlled fraction in any downstream use; do",
        "not present the corpus as a fully observed real-world corpus.",
        "",
    ]
    path = release_root / "dataset_card.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = {
        "schema_version": "agentready.data_foundry.dataset_card.v1",
        "generated_at": now_utc(),
        "product_id": product_id,
        "total_records": total,
        "natural_records": natural,
        "controlled_records": controlled,
        "controlled_pct": controlled_pct,
        "path": rel(root, path),
    }
    write_json(report_data_foundry_path(root, "cerberus-dataset-card-latest.json"), report)
    return report


def dataset_card_gate(release_root: Path) -> tuple[bool, str, Any]:
    path = release_root / "dataset_card.md"
    if not path.exists():
        return (False, "Dataset card not emitted; run emit-dataset-card after label gates pass.", None)
    text = path.read_text(encoding="utf-8")
    required_markers = ["## Provenance", "CONTROLLED_CASE", "SUPPORTED_CLAIM", "Natural"]
    missing = [marker for marker in required_markers if marker not in text]
    if missing:
        return (False, "Dataset card is missing required provenance-disclosure sections.", {"missing": missing})
    return (True, "Dataset card present with explicit provenance disclosure.", None)


def label_taxonomy_gate(release_root: Path) -> tuple[bool, str, Any]:
    path = release_root / "label_taxonomy.json"
    data = read_json(path)
    if not data:
        return (False, "Label taxonomy not emitted; run emit-label-taxonomy after label gates pass.", None)
    labels = as_dict(data.get("labels"))
    missing = [label for label in CERBERUS_REQUIRED_LABELS if label not in labels]
    if missing:
        return (False, "Label taxonomy does not declare every required label.", {"missing": missing})
    incomplete = [
        label
        for label in CERBERUS_REQUIRED_LABELS
        if not (labels.get(label, {}).get("definition") and labels.get(label, {}).get("gold_verdict"))
    ]
    if incomplete:
        return (False, "Label taxonomy entries are missing a definition or gold verdict.", {"incomplete": incomplete})
    return (True, "Label taxonomy declares every required label with a definition and gold verdict.", None)
