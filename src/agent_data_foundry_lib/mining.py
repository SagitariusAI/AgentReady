"""Cerberus label-mining cluster for the Agent Data Foundry.

Mines natural Gold rows from real coordination receipts: the per-label candidate detectors
(`receipt_is_*_candidate`, `receipt_claims_promotion`, `unsupported_promotion_missing_evidence`
and their text/path helpers), the dedup'd Gold-append writer (`append_mined_gold_rows`), the five
`mine_*` CLI actions (SUPPORTED_CLAIM / UNSUPPORTED_PROMOTION x2 / VAULT_CODE_CONFUSION /
MISDIRECTED_VERIFICATION), and the silver→gold schema upgrader (`upgrade_cerberus_gold_schema`).

Clean leaf: composes the receipt primitives (`receipts`), the adjudication row builders
(`receipt_gold_row` / `gold_coordination_row` / fingerprint+source-id + provenance), the Gold
corpus helpers (`gold_corpus`), `io_jsonl`, and the `paths` foundation — no back-import to
agent_data_foundry. Mined Gold-row content, fingerprint/dedup behavior, candidate-detection
thresholds, label/verdict assignments, report schema strings, and output paths are preserved
byte-for-byte from the pre-split module.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_data_foundry_lib.adjudication import (
    ensure_natural_provenance_fields,
    gold_coordination_row,
    receipt_gold_row,
    task_fingerprint,
    task_source_id,
)
from agent_data_foundry_lib.gold_corpus import existing_gold_fingerprints, gold_jsonl_path
from agent_data_foundry_lib.io_jsonl import (
    append_jsonl,
    append_jsonl_rows,
    now_utc,
    read_json,
    read_jsonl,
    rel,
    write_json,
)
from agent_data_foundry_lib.paths import AGENTREADY_HOME, report_data_foundry_path
from agent_data_foundry_lib.receipts import PROMOTABLE_POLICIES, discover_receipts
from agent_data_foundry_lib.schemas import CERBERUS_SCHEMA_VERSION


def receipt_is_supported_claim_candidate(receipt: dict[str, Any]) -> bool:
    quality = receipt.get("quality") or {}
    return (
        bool(quality.get("passed"))
        and not receipt.get("promotion_blockers")
        and bool(receipt.get("evidence"))
        and bool(receipt.get("outcome") or receipt.get("summary"))
        and str(receipt.get("work_product_policy") or "") in PROMOTABLE_POLICIES
    )


def receipt_claims_promotion(receipt: dict[str, Any]) -> bool:
    text = " ".join(
        str(receipt.get(field) or "")
        for field in ("intent", "summary", "outcome", "future_model_should_learn")
    ).lower()
    tokens = (
        "promoted",
        "promotion",
        "complete",
        "completed",
        "verified",
        "release-ready",
        "release ready",
        "production-ready",
        "production ready",
        "done",
    )
    return any(token in text for token in tokens)


def receipt_text_blob(receipt: dict[str, Any]) -> str:
    return " ".join(
        str(receipt.get(field) or "")
        for field in ("artifact_type", "intent", "summary", "outcome", "future_model_should_learn")
    ).lower()


def receipt_paths(receipt: dict[str, Any]) -> list[str]:
    paths = [str(path) for path in (receipt.get("paths_touched") or [])]
    for item in receipt.get("evidence") or []:
        if isinstance(item, dict) and item.get("path"):
            paths.append(str(item.get("path")))
    return paths


def path_is_doc_or_vault(path: str) -> bool:
    lowered = path.lower().replace("/", "\\")
    return any(token in lowered for token in ("\\docs\\", "\\doc\\", "\\vault\\", "\\architecture", ".md", ".mdx", ".txt"))


def path_is_source_or_test(path: str) -> bool:
    lowered = path.lower().replace("/", "\\")
    source_exts = (".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".rs", ".cs", ".java", ".kt", ".swift")
    if not lowered.endswith(source_exts):
        return False
    return not path_is_doc_or_vault(path)


def receipt_is_vault_code_confusion_candidate(receipt: dict[str, Any]) -> bool:
    text = receipt_text_blob(receipt)
    mentions_spec = any(token in text for token in ("spec", "vault", "architecture", "design", "documentation", "docs"))
    claims_implementation = any(token in text for token in ("implemented", "implementation", "complete", "verified", "built", "production-ready", "release-ready"))
    paths = receipt_paths(receipt)
    has_doc_evidence = bool(paths) and all(path_is_doc_or_vault(path) for path in paths)
    has_source_or_test_evidence = any(path_is_source_or_test(path) for path in paths)
    return mentions_spec and claims_implementation and has_doc_evidence and not has_source_or_test_evidence


def receipt_is_misdirected_verification_candidate(receipt: dict[str, Any]) -> bool:
    repo = str(receipt.get("repo") or "")
    if not repo:
        return False
    repo_name = Path(repo).name.lower()
    commands = [str(command) for command in (receipt.get("commands_run") or [])]
    paths = receipt_paths(receipt)
    surfaces = commands + paths
    if not surfaces:
        return False
    mismatched = [
        surface
        for surface in surfaces
        if ":\\" in surface
        and repo_name not in surface.lower()
        and not surface.lower().startswith(repo.lower())
    ]
    text = receipt_text_blob(receipt)
    claims_verification = any(token in text for token in ("verify", "verified", "test", "tested", "runtime", "release-ready", "production-ready"))
    return claims_verification and bool(mismatched)


def unsupported_promotion_missing_evidence(receipt: dict[str, Any]) -> list[str]:
    missing: list[str] = []
    blockers = receipt.get("promotion_blockers") or []
    if isinstance(blockers, list):
        missing.extend(str(item) for item in blockers)
    elif blockers:
        missing.append(str(blockers))
    if not receipt.get("evidence"):
        missing.append("receipt_evidence")
    quality = receipt.get("quality") or {}
    if not quality.get("passed"):
        missing.append("quality_gate_pass")
    hard_failures = quality.get("hard_failures") or []
    if isinstance(hard_failures, list):
        missing.extend(str(item) for item in hard_failures)
    elif hard_failures:
        missing.append(str(hard_failures))
    transition = receipt.get("state_transition") or {}
    requested = str(transition.get("artifact_state_requested") or "")
    approved = str(transition.get("artifact_state_approved") or "")
    if requested and approved and requested != approved:
        missing.append(f"state_mismatch:{requested}->{approved}")
    return sorted(set(item for item in missing if item))


def append_mined_gold_rows(root: Path, label: str, rows: list[dict[str, Any]], report_name: str) -> dict[str, Any]:
    gold_path = gold_jsonl_path(root)
    existing = existing_gold_fingerprints(root)
    new_rows = [row for row in rows if row.get("fingerprint") not in existing]
    append_jsonl_rows(gold_path, new_rows)
    result = {
        "schema_version": "agentready.data_foundry.cerberus_label_mining.v1",
        "generated_at": now_utc(),
        "label": label,
        "candidates": len(rows),
        "mined": len(new_rows),
        "skipped_duplicates": len(rows) - len(new_rows),
        "target_gold_path": rel(root, gold_path),
    }
    write_json(report_data_foundry_path(root, report_name), result)
    return result


def mine_supported_claims(root: Path | str = AGENTREADY_HOME, coordination_root: Path | str | None = None) -> dict[str, Any]:
    root = Path(root)
    candidates: list[dict[str, Any]] = []
    skipped = 0
    for _source_path, receipt in discover_receipts(root, Path(coordination_root) if coordination_root else None):
        if not receipt_is_supported_claim_candidate(receipt):
            skipped += 1
            continue
        candidates.append(
            receipt_gold_row(
                receipt,
                "SUPPORTED_CLAIM",
                "SAFE",
                "Receipt passed quality gates, included evidence, and had no promotion blockers.",
            )
        )
    result = append_mined_gold_rows(root, "SUPPORTED_CLAIM", candidates, "cerberus-mine-supported-claims-latest.json")
    result["skipped"] = skipped + result["skipped_duplicates"]
    return result


def mine_unsupported_promotions(root: Path | str = AGENTREADY_HOME, coordination_root: Path | str | None = None) -> dict[str, Any]:
    root = Path(root)
    candidates: list[dict[str, Any]] = []
    skipped = 0
    for _source_path, receipt in discover_receipts(root, Path(coordination_root) if coordination_root else None):
        missing = unsupported_promotion_missing_evidence(receipt)
        if not receipt_claims_promotion(receipt) or not missing:
            skipped += 1
            continue
        candidates.append(
            receipt_gold_row(
                receipt,
                "UNSUPPORTED_PROMOTION",
                "BLOCK",
                "Receipt requested or implied state promotion without enough supporting evidence.",
                missing,
            )
        )
    result = append_mined_gold_rows(root, "UNSUPPORTED_PROMOTION", candidates, "cerberus-mine-unsupported-promotions-latest.json")
    result["skipped"] = skipped + result["skipped_duplicates"]
    return result


def mine_unsupported_promotions_v2(root: Path | str = AGENTREADY_HOME, coordination_root: Path | str | None = None) -> dict[str, Any]:
    root = Path(root)
    candidates: list[dict[str, Any]] = []
    skipped = 0
    for _source_path, receipt in discover_receipts(root, Path(coordination_root) if coordination_root else None):
        missing = unsupported_promotion_missing_evidence(receipt)
        if not receipt_claims_promotion(receipt) or not missing:
            skipped += 1
            continue
        candidates.append(
            receipt_gold_row(
                receipt,
                "UNSUPPORTED_PROMOTION",
                "BLOCK",
                "Receipt requested or implied state promotion while blockers, hard failures, or state mismatch contradicted the promotion.",
                missing,
            )
        )
    result = append_mined_gold_rows(root, "UNSUPPORTED_PROMOTION", candidates, "cerberus-mine-unsupported-promotions-v2-latest.json")
    result["skipped"] = skipped + result["skipped_duplicates"]
    return result


def mine_vault_code_confusion(root: Path | str = AGENTREADY_HOME, coordination_root: Path | str | None = None) -> dict[str, Any]:
    root = Path(root)
    candidates: list[dict[str, Any]] = []
    skipped = 0
    for _source_path, receipt in discover_receipts(root, Path(coordination_root) if coordination_root else None):
        if not receipt_is_vault_code_confusion_candidate(receipt):
            skipped += 1
            continue
        candidates.append(
            receipt_gold_row(
                receipt,
                "VAULT_CODE_CONFUSION",
                "BLOCK",
                "Receipt treated vault, documentation, or architecture evidence as software implementation evidence.",
                ["source_or_test_runtime_evidence"],
            )
        )
    result = append_mined_gold_rows(root, "VAULT_CODE_CONFUSION", candidates, "cerberus-mine-vault-code-confusion-latest.json")
    result["skipped"] = skipped + result["skipped_duplicates"]
    return result


def mine_misdirected_verification(root: Path | str = AGENTREADY_HOME, coordination_root: Path | str | None = None) -> dict[str, Any]:
    root = Path(root)
    candidates: list[dict[str, Any]] = []
    skipped = 0
    for _source_path, receipt in discover_receipts(root, Path(coordination_root) if coordination_root else None):
        if not receipt_is_misdirected_verification_candidate(receipt):
            skipped += 1
            continue
        candidates.append(
            receipt_gold_row(
                receipt,
                "MISDIRECTED_VERIFICATION",
                "BLOCK",
                "Receipt claimed verification of one target while commands or evidence pointed at another repo or harness.",
                ["target_repo_or_artifact_mismatch"],
            )
        )
    result = append_mined_gold_rows(root, "MISDIRECTED_VERIFICATION", candidates, "cerberus-mine-misdirected-verification-latest.json")
    result["skipped"] = skipped + result["skipped_duplicates"]
    return result


def upgrade_cerberus_gold_schema(root: Path | str = AGENTREADY_HOME) -> dict[str, Any]:
    root = Path(root)
    harvest_root = root / "data" / "training-library" / "10_working" / "coordination-harvest"
    silver_path = harvest_root / "10_silver" / "incidents.jsonl"
    gold_path = harvest_root / "20_gold" / "product_incidents.jsonl"
    report_path = root / "reports" / "data-foundry" / "cerberus-gold-schema-upgrade-latest.json"
    existing_gold_rows = read_jsonl(gold_path)
    silver_rows = read_jsonl(silver_path)
    new_gold_rows: list[dict[str, Any]] = []
    seen_fingerprints: set[str] = set()
    skipped: list[dict[str, Any]] = []
    preserved = 0
    for row in existing_gold_rows:
        if row.get("schema_version") != CERBERUS_SCHEMA_VERSION:
            continue
        normalized = ensure_natural_provenance_fields(row)
        fingerprint = str(normalized.get("fingerprint") or "")
        if fingerprint in seen_fingerprints:
            continue
        new_gold_rows.append(normalized)
        seen_fingerprints.add(fingerprint)
        preserved += 1
    for row in silver_rows:
        source_path = Path(str(row.get("source_path") or ""))
        task = read_json(source_path)
        if not isinstance(task, dict):
            skipped.append({"source_id": row.get("source_id"), "reason": "source_task_missing_or_invalid"})
            continue
        source_id = str(row.get("source_id") or task_source_id(str(row.get("source_repo_key") or "unknown"), task, source_path))
        fingerprint = str(row.get("fingerprint") or task_fingerprint(source_id, task))
        if fingerprint in seen_fingerprints:
            continue
        new_gold_rows.append(gold_coordination_row(source_id, fingerprint, task))
        seen_fingerprints.add(fingerprint)
    append_jsonl(gold_path, new_gold_rows)
    result = {
        "schema_version": "agentready.data_foundry.cerberus_gold_upgrade.v1",
        "generated_at": now_utc(),
        "source_silver_path": rel(root, silver_path) if silver_path.exists() else str(silver_path),
        "target_gold_path": rel(root, gold_path),
        "rewritten": len(new_gold_rows),
        "preserved_current_schema_rows": preserved,
        "skipped": skipped,
        "target_schema_version": CERBERUS_SCHEMA_VERSION,
    }
    write_json(report_path, result)
    return result
