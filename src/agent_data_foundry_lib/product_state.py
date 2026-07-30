# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Product State Scanner + Product Reality Brief for the Agent Data Foundry."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from agent_data_foundry_lib.io_jsonl import _sha256_text, now_utc, read_json, rel, write_json
from agent_data_foundry_lib.paths import AGENTREADY_HOME
from agent_data_foundry_lib.safety_scan import _scan_source_signal_value

PRODUCT_STATE_LEDGER_SCHEMA_VERSION = "sf.product_state_ledger.v0.1"
_PS_STATUSES = (
    "IDEA", "DEFINED", "PLANNED", "IN_PROGRESS", "PARTIAL", "BUILT", "TESTED",
    "PACKAGED", "RELEASE_CANDIDATE", "PRODUCTION_READY", "DEPRECATED", "BLOCKED", "SEALED",
)
_PS_EVIDENCE_TAGS = (
    "DOC_DEFINED_ONLY", "CODE_EXISTS", "TEST_EXISTS", "GATE_GREEN", "PACKAGED",
    "RUNTIME_SMOKE_PASSED", "USER_WORKFLOW_VERIFIED", "OWNER_ACCEPTED",
    "COMMERCIAL_CLEARANCE_PENDING",
)
_PS_COMMERCIAL = ("pending", "cleared", "not_applicable")


def product_state_root(root: Path | str) -> Path:
    return Path(root) / "data" / "training-library" / "30_curated" / "internal" / "product-state"


# Declared components. The scanner DISCOVERS evidence for each at scan time; it
# never asserts a status the evidence does not support.
_PRODUCT_STATE_COMPONENTS: list[dict[str, Any]] = [
    {"component_id": "data_foundry.claim_evidence_sentinel.exporter", "component_name": "ClaimEvidence Sentinel training exporter", "subsystem": "data_foundry", "kind": "code",
     "code": [("src/agent_data_foundry_lib/training_export.py", "export_claim_evidence_sentinel_training")], "tests": ["test_export_claim_evidence_sentinel_training", "test_sft_format_strict_sentinel_json"],
     "docs": ["docs/LOCAL_MODEL_IMPROVEMENT_CYCLE_DOCTRINE.md"], "commit_grep": "Dataset Training Exporter"},
    {"component_id": "data_foundry.claim_evidence_sentinel.eval_gate", "component_name": "ClaimEvidence Sentinel eval + promotion gate", "subsystem": "data_foundry", "kind": "code",
     "code": [("src/agent_data_foundry_lib/eval_gate.py", "claim_evidence_sentinel_eval_and_gate")], "tests": ["test_eval_gate_perfect_predictions_promoted", "test_eval_gate_baseline_required"],
     "docs": ["docs/LOCAL_MODEL_IMPROVEMENT_CYCLE_DOCTRINE.md"], "commit_grep": "Eval + Promotion Gate"},
    {"component_id": "data_foundry.creator_provenance", "component_name": "Creator Provenance Envelope", "subsystem": "data_foundry", "kind": "code",
     "code": [("src/agent_data_foundry_lib/provenance.py", "build_creator_provenance_envelope")], "tests": ["test_provenance_present_on_every_exported_row"],
     "docs": ["docs/LOCAL_MODEL_IMPROVEMENT_CYCLE_DOCTRINE.md"], "commit_grep": "Creator Provenance Envelope"},
    {"component_id": "data_foundry.claim_evidence_sentinel.baseline_eval", "component_name": "ClaimEvidence Sentinel baseline eval", "subsystem": "data_foundry", "kind": "code",
     "code": [("src/agent_data_foundry_lib/eval_gate.py", "claim_evidence_sentinel_baseline_eval")], "tests": ["test_baseline_eval_metrics_and_outputs"],
     "docs": ["docs/LOCAL_MODEL_IMPROVEMENT_CYCLE_DOCTRINE.md"]},
    {"component_id": "product_state.scanner", "component_name": "Product State Scanner + Reality Brief Runner", "subsystem": "product_delivery", "kind": "code",
     "code": [("src/agent_data_foundry_lib/product_state.py", "product_state_scan")], "tests": ["test_product_state_scan_outputs_and_schema", "test_classify_product_status_bar"],
     "docs": ["docs/workers/PRODUCT_STATE_CARTOGRAPHER_WORKER_CARD.md"]},
    {"component_id": "governance.metadata_header_standard", "component_name": "Factory Metadata Header Standard", "subsystem": "governance", "kind": "doc",
     "docs": ["docs/FACTORY_METADATA_HEADER_STANDARD.md"]},
    {"component_id": "governance.sop_library", "component_name": "Software Factory SOP Library", "subsystem": "governance", "kind": "doc",
     "docs": ["docs/10_sops/README.md"]},
    {"component_id": "governance.documentation_optimization_doctrine", "component_name": "Documentation Optimization Doctrine (Van der Cleef)", "subsystem": "governance", "kind": "doc",
     "docs": ["docs/FACTORY_DOCUMENTATION_OPTIMIZATION_DOCTRINE.md"]},
    {"component_id": "workers.obsidian_vault_steward", "component_name": "Obsidian Vault Steward worker", "subsystem": "docs_governance", "kind": "doc",
     "docs": ["docs/workers/OBSIDIAN_VAULT_STEWARD_WORKER_CARD.md"]},
    {"component_id": "workers.product_state_cartographer", "component_name": "Product State Cartographer worker", "subsystem": "product_delivery", "kind": "doc",
     "docs": ["docs/workers/PRODUCT_STATE_CARTOGRAPHER_WORKER_CARD.md"]},
    {"component_id": "local_model.training_loop", "component_name": "Local-model training/adapter loop", "subsystem": "data_foundry", "kind": "plan",
     "docs": ["docs/LOCAL_MODEL_COMPLETION_ROADMAP.md"]},
]


def _ps_symbol_in_file(path: Path, symbol: str) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    return bool(
        re.search(rf"\b(?:def|class)\s+{re.escape(symbol)}\b", text)
        or re.search(rf"^{re.escape(symbol)}\s*=", text, re.M)
    )


def _ps_doc_is_sealed(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^﻿?---\n(.*?)\n---", text, re.S)
    if not m:
        return False
    fm = m.group(1)
    return bool(re.search(r"^status:\s*sealed\s*$", fm, re.M) or re.search(r"^lifecycle:\s*sealed\s*$", fm, re.M))


def _ps_gate_is_green(root: Path) -> bool:
    data = read_json(Path(root) / ".agentready" / "gate_status.json")
    return bool(isinstance(data, dict) and str(data.get("status")) == "pass")


def _ps_tests_contain(root: Path, patterns: list[str]) -> list[str]:
    tests_dir = Path(root) / "tests"
    if not patterns or not tests_dir.exists():
        return []
    blob = "".join(p.read_text(encoding="utf-8", errors="replace") for p in sorted(tests_dir.glob("test_*.py")))
    return [pat for pat in patterns if pat in blob]


def _ps_git_commits(root: Path, grep: str | None, limit: int = 3) -> list[str]:
    if not grep:
        return []
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", "--oneline", "-n", str(limit), f"--grep={grep}"],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    if out.returncode != 0:
        return []
    return [ln.split()[0] for ln in out.stdout.strip().splitlines() if ln.strip()]


def _classify_product_status(tags: set[str], kind: str) -> str:
    """The evidence bar. A well-defined document is not proof of implementation:
    docs alone never reach BUILT. PRODUCTION_READY / RELEASE_CANDIDATE are never
    inferred by the scanner (they need human/owner gates)."""
    if "SEALED" in tags:
        return "SEALED"
    if {"CODE_EXISTS", "TEST_EXISTS", "GATE_GREEN"} <= tags:
        return "TESTED"
    if {"CODE_EXISTS", "GATE_GREEN"} <= tags:
        return "BUILT"
    if "CODE_EXISTS" in tags:
        return "IN_PROGRESS"
    if "PACKAGED" in tags:
        return "PACKAGED"
    if "DOC_DEFINED_ONLY" in tags:
        return "PLANNED" if kind == "plan" else "DEFINED"
    return "IDEA"


def _scan_product_component(root: Path, spec: dict[str, Any], gate_green: bool) -> dict[str, Any]:
    root = Path(root)
    tags: set[str] = set()
    evidence: list[dict[str, Any]] = []
    related_docs = [d for d in spec.get("docs", []) if (root / d).exists()]
    if related_docs:
        tags.add("DOC_DEFINED_ONLY")
        evidence.append({"tag": "DOC_DEFINED_ONLY", "ref": related_docs[0], "note": None})
    code_hit = next((f"{f}:{sym}" for (f, sym) in spec.get("code", []) if _ps_symbol_in_file(root / f, sym)), None)
    if code_hit:
        tags.add("CODE_EXISTS")
        evidence.append({"tag": "CODE_EXISTS", "ref": code_hit, "note": None})
    test_hits = _ps_tests_contain(root, spec.get("tests", []))
    related_tests = [f"tests/test_agent_data_foundry.py::{h}" for h in test_hits]
    if test_hits:
        tags.add("TEST_EXISTS")
        evidence.append({"tag": "TEST_EXISTS", "ref": related_tests[0], "note": None})
    if code_hit and gate_green:
        tags.add("GATE_GREEN")
        evidence.append({"tag": "GATE_GREEN", "ref": ".agentready/gate_status.json", "note": "repo gate pass"})
    packaged_globs = spec.get("packaged_glob") or []
    if isinstance(packaged_globs, str):
        packaged_globs = [packaged_globs]
    if any(any(root.glob(g)) for g in packaged_globs):
        tags.add("PACKAGED")
        evidence.append({"tag": "PACKAGED", "ref": next(g for g in packaged_globs if any(root.glob(g))), "note": None})
    sealed = any((root / d).exists() and _ps_doc_is_sealed(root / d) for d in spec.get("docs", []))
    sealed_globs = spec.get("sealed_glob") or []
    if isinstance(sealed_globs, str):
        sealed_globs = [sealed_globs]
    sealed = sealed or any(any(root.glob(g)) for g in sealed_globs)
    sealed_ref: str | None = None
    if sealed:
        tags.add("SEALED")  # a STATUS, not an evidence_tag -- recorded as a receipt, not in `evidence`
        sealed_ref = next((d for d in spec.get("docs", []) if (root / d).exists() and _ps_doc_is_sealed(root / d)), None) \
            or next((g for g in sealed_globs if any(root.glob(g))), None) or "sealed record"
    commercial = spec.get("commercial", "not_applicable")
    if commercial == "pending":
        tags.add("COMMERCIAL_CLEARANCE_PENDING")

    status = _classify_product_status(tags, str(spec.get("kind", "doc")))
    not_yet: list[str] = []
    if "CODE_EXISTS" not in tags and spec.get("kind") == "code":
        not_yet.append("no code artifact yet")
    if "TEST_EXISTS" not in tags:
        not_yet.append("no tests")
    if "GATE_GREEN" not in tags:
        not_yet.append("no gate-green receipt")
    if "PACKAGED" not in tags:
        not_yet.append("not packaged")
    if "RUNTIME_SMOKE_PASSED" not in tags:
        not_yet.append("no runtime smoke")
    if "OWNER_ACCEPTED" not in tags:
        not_yet.append("no explicit owner acceptance")
    related_receipts: list[str] = []
    if "GATE_GREEN" in tags:
        related_receipts.append(".agentready/gate_status.json")
    if sealed_ref:
        related_receipts.append(f"sealed:{sealed_ref}")
    return {
        "component_id": spec["component_id"],
        "component_name": spec["component_name"],
        "status": status,
        "evidence_tags": [t for t in _PS_EVIDENCE_TAGS if t in tags],
        "evidence": evidence,
        "blocked_by": spec.get("blocked_by"),
        "not_yet": not_yet,
        "related_docs": related_docs,
        "related_commits": _ps_git_commits(root, spec.get("commit_grep")),
        "related_tests": related_tests,
        "related_receipts": related_receipts,
        "owner_acceptance": None,
        "commercial_clearance": commercial if commercial in _PS_COMMERCIAL else "not_applicable",
        "last_verified_at": now_utc(),
        "verifier": "product_state_scanner",
    }


def _validate_ledger_draft(draft: dict[str, Any]) -> tuple[bool, list[str]]:
    """Manual, dependency-free conformance check against sf.product_state_ledger.v0.1."""
    errors: list[str] = []
    if draft.get("schema_version") != PRODUCT_STATE_LEDGER_SCHEMA_VERSION:
        errors.append("schema_version mismatch")
    required_top = {"schema_version", "product", "subsystem", "updated_at", "components"}
    if not required_top <= set(draft):
        errors.append(f"missing top keys: {required_top - set(draft)}")
    comp_keys = {"component_id", "component_name", "status", "evidence_tags", "evidence", "blocked_by",
                 "not_yet", "related_docs", "related_commits", "related_tests", "related_receipts",
                 "owner_acceptance", "commercial_clearance", "last_verified_at", "verifier"}
    for c in draft.get("components", []):
        if set(c) != comp_keys:
            errors.append(f"{c.get('component_id')}: key set mismatch")
        if c.get("status") not in _PS_STATUSES:
            errors.append(f"{c.get('component_id')}: bad status {c.get('status')}")
        if any(t not in _PS_EVIDENCE_TAGS for t in c.get("evidence_tags", [])):
            errors.append(f"{c.get('component_id')}: bad evidence tag")
        for ev in c.get("evidence", []):
            if not isinstance(ev, dict) or ev.get("tag") not in _PS_EVIDENCE_TAGS or "ref" not in ev:
                errors.append(f"{c.get('component_id')}: bad evidence item")
        if c.get("commercial_clearance") not in _PS_COMMERCIAL:
            errors.append(f"{c.get('component_id')}: bad commercial_clearance")
    return (not errors, errors)


def _product_reality_brief_md(draft: dict[str, Any]) -> str:
    comps = draft["components"]

    def by(*statuses: str) -> list[dict[str, Any]]:
        return [c for c in comps if c["status"] in statuses]

    def names(rows: list[dict[str, Any]]) -> str:
        return "\n".join(f"- **{c['component_name']}** (`{c['status']}`) — evidence: {', '.join(c['evidence_tags']) or 'none'}" for c in rows) or "- (none)"

    doc_only = [c for c in comps if c["status"] in ("DEFINED", "PLANNED") and "DOC_DEFINED_ONLY" in c["evidence_tags"]]
    lines = [
        "# Product Reality Brief",
        "",
        "> Generated by the **Product State Scanner** (dry-run, evidence-derived). "
        "A well-defined document is not proof of implementation. "
        "**Sell-ready / commercial-ready is a separate owner/legal/business gate and is NOT asserted here.**",
        "",
        f"- **Product / subsystem:** {draft['product']} / (all subsystems)",
        f"- **Generated at:** {draft['updated_at']}",
        "- **Current task boundary:** evidence scan only; no status was upgraded without evidence.",
        "",
        "## Built components", names(by("BUILT")),
        "", "## Tested components", names(by("TESTED")),
        "", "## Packaged components", names(by("PACKAGED")),
        "", "## Partial / in-progress components", names(by("PARTIAL", "IN_PROGRESS")),
        "", "## Defined-but-not-built components", names(doc_only),
        "", "## Blocked components", names(by("BLOCKED")),
        "", "## Sealed artifacts", names(by("SEALED")),
        "", "## Evidence",
    ]
    for c in comps:
        refs = "; ".join(f"{e['tag']}:{e['ref']}" for e in c["evidence"]) or "none"
        commits = (", commits " + ", ".join(c["related_commits"])) if c["related_commits"] else ""
        lines.append(f"- **{c['component_name']}** — {refs}{commits}")
    lines += ["", "## Warnings about doc-only claims"]
    if doc_only:
        for c in doc_only:
            lines.append(f"- **{c['component_name']}** is `{c['status']}` (DOC_DEFINED_ONLY) — a spec/roadmap, NOT built. Do not treat it as an implementation.")
    else:
        lines.append("- (none)")
    lines += ["", "## Current unknowns"]
    for c in comps:
        if c["not_yet"]:
            lines.append(f"- **{c['component_name']}**: {', '.join(c['not_yet'])}")
    lines += ["", "## Recommended verification targets before frontier model work",
              "- Run the focused tests and confirm the gate marker is green before claiming any `BUILT`/`TESTED` status.",
              "- For any `DEFINED`/`PLANNED` target, treat it as not-yet-built; gather code + receipt evidence first.",
              "- Never claim `RELEASE_CANDIDATE`/`PRODUCTION_READY`/sell-ready without the corresponding gates and owner approval."]
    return "\n".join(lines) + "\n"


def product_state_scan(root: Path | str = AGENTREADY_HOME, components: list[dict[str, Any]] | None = None,
                       output_path: str | Path | None = None) -> dict[str, Any]:
    """Deterministic, dry-run/report-only product-state scan. Emits a
    schema-conformant ledger DRAFT, a Product Reality Brief, an evidence report,
    and a gap report. No live model, no status upgrade without evidence, no
    40_release_ready writes, no release/commercial claims."""
    root = Path(root)
    specs = components if components is not None else _PRODUCT_STATE_COMPONENTS
    out_dir = Path(output_path) if output_path else product_state_root(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    gate_green = _ps_gate_is_green(root)
    entries = [_scan_product_component(root, s, gate_green) for s in specs]
    draft = {
        "schema_version": PRODUCT_STATE_LEDGER_SCHEMA_VERSION,
        "product": "Software Factory",
        "subsystem": None,
        "updated_at": now_utc(),
        "components": entries,
    }
    schema_valid, schema_errors = _validate_ledger_draft(draft)
    status_dist: dict[str, int] = {}
    for e in entries:
        status_dist[e["status"]] = status_dist.get(e["status"], 0) + 1

    write_json(out_dir / "product_state_ledger_draft.json", draft)
    write_json(out_dir / "product_state_evidence_report.json", {
        "schema_version": "sf.product_state_evidence.v0.1",
        "generated_at": now_utc(),
        "gate_green": gate_green,
        "components": [{"component_id": e["component_id"], "status": e["status"],
                        "evidence_tags": e["evidence_tags"], "evidence": e["evidence"]} for e in entries],
    })
    write_json(out_dir / "product_state_gap_report.json", {
        "schema_version": "sf.product_state_gap.v0.1",
        "generated_at": now_utc(),
        "gaps": [{"component_id": e["component_id"], "status": e["status"], "missing": e["not_yet"]}
                 for e in entries if e["not_yet"]],
    })
    (out_dir / "product_reality_brief.md").write_text(_product_reality_brief_md(draft), encoding="utf-8")

    return {
        "status": "SCANNED",
        "mode": "dry_run",
        "components_scanned": len(entries),
        "status_distribution": status_dist,
        "gate_green": gate_green,
        "schema_valid": schema_valid,
        "schema_errors": schema_errors,
        "model_wiring_performed": False,
        "wrote_release_ready": False,
        "output_root": rel(root, out_dir),
    }


# ---- Product Reality Brief Chat Post v0.1 ---------------------------------
# Deterministic report/post mode. Default is file-only / dry-run; chat posting
# requires an explicit brief_mode (chat|both). Connector-agnostic: an injectable
# chat_poster is called only when present; otherwise a POST-READY artifact is
# emitted and the status is CHAT_UNAVAILABLE -- never a fake POSTED. Posting is
# advisory and NEVER modifies product state, writes under 40_release_ready, or
# makes a release/commercial claim.

PRODUCT_REALITY_BRIEF_POST_SCHEMA = "sf.product_reality_brief_post.v0.1"


def _brief_counts(draft: dict[str, Any] | None) -> tuple[int, int, int]:
    comps = draft.get("components", []) if isinstance(draft, dict) else []
    defined_not_built = sum(1 for c in comps if c.get("status") in ("DEFINED", "PLANNED") and "DOC_DEFINED_ONLY" in c.get("evidence_tags", []))
    blocked = sum(1 for c in comps if c.get("status") == "BLOCKED")
    sealed = sum(1 for c in comps if c.get("status") == "SEALED")
    return defined_not_built, blocked, sealed


def product_reality_brief_post(root: Path | str = AGENTREADY_HOME, brief_mode: str = "file",
                               regenerate: bool = False, chat_poster: Any = None,
                               output_path: str | Path | None = None) -> dict[str, Any]:
    """Deliver the Product Reality Brief to chat (or prepare it). file (default) =
    receipt only; chat|both = attempt a post via `chat_poster`, else emit a
    POST-READY artifact and record CHAT_UNAVAILABLE. Never claims POSTED without a
    confirmed message_id; never posts a brief with a severe secret finding; a
    missing brief fails safely; posting never mutates product state."""
    root = Path(root)
    out_dir = Path(output_path) if output_path else product_state_root(root)
    out_dir.mkdir(parents=True, exist_ok=True)
    if regenerate:
        product_state_scan(root, output_path=out_dir)
    mode = brief_mode if brief_mode in ("file", "chat", "both") else "file"
    brief_path = out_dir / "product_reality_brief.md"
    draft_path = out_dir / "product_state_ledger_draft.json"

    def _write_receipt(**kw: Any) -> dict[str, Any]:
        receipt = {
            "schema_version": PRODUCT_REALITY_BRIEF_POST_SCHEMA,
            "action": "product-reality-brief",
            "mode": mode,
            "brief_path": rel(root, brief_path),
            "brief_sha256": None,
            "scan_run_id": None,
            "post_status": None,
            "posted_at": None,
            "channel": None,
            "message_id": None,
            "dry_run": True,
            "product": None,
            "subsystem": None,
            "warnings_count": 0,
            "defined_not_built_count": 0,
            "blocked_count": 0,
            "sealed_count": 0,
            "generated_at": now_utc(),
            "model_wiring_performed": False,
            "wrote_release_ready": False,
            "modified_product_state": False,
        }
        receipt.update(kw)
        write_json(out_dir / "product_reality_brief_post_receipt.json", receipt)
        return receipt

    if not brief_path.exists():
        receipt = _write_receipt(post_status="MISSING_BRIEF")
        return {"status": "INCOMPLETE", "post_status": "MISSING_BRIEF", "ok": False, "receipt": receipt, "output_root": rel(root, out_dir)}

    brief_text = brief_path.read_text(encoding="utf-8")
    brief_sha = _sha256_text(brief_text)
    draft = read_json(draft_path) if draft_path.exists() else None
    scan_run_id = _sha256_text(draft_path.read_text(encoding="utf-8"))[:16] if draft_path.exists() else None
    defined_not_built, blocked, sealed = _brief_counts(draft)
    product = draft.get("product") if isinstance(draft, dict) else None
    subsystem = draft.get("subsystem") if isinstance(draft, dict) else None
    has_doc_only_warnings = "## Warnings about doc-only claims" in brief_text
    counts = {"product": product, "subsystem": subsystem, "warnings_count": defined_not_built,
              "defined_not_built_count": defined_not_built, "blocked_count": blocked, "sealed_count": sealed}

    # Secret gate: never post hidden secrets.
    _cleaned, _findings, _redacted, severe = _scan_source_signal_value(brief_text)
    if severe:
        receipt = _write_receipt(post_status="SECRET_BLOCKED", brief_sha256=brief_sha, scan_run_id=scan_run_id, **counts)
        return {"status": "INCOMPLETE", "post_status": "SECRET_BLOCKED", "ok": False, "receipt": receipt, "output_root": rel(root, out_dir)}

    post_status, posted_at, channel, message_id, dry_run = "FILE_ONLY", None, None, None, True
    if mode in ("chat", "both"):
        if chat_poster is None:
            post_status = "CHAT_UNAVAILABLE"
            ready = ("# Product Reality Brief -- POST-READY (not sent)\n\n"
                     "> Chat connector unavailable. This message is ready to post to the internal "
                     "coordination room before frontier model work begins.\n\n" + brief_text)
            (out_dir / "product_reality_brief_post_ready.md").write_text(ready, encoding="utf-8")
        else:
            try:
                result = chat_poster(brief_text) or {}
            except Exception:  # noqa: BLE001 -- a connector error must not crash the runner
                result = {}
            if result.get("ok") and result.get("message_id"):  # POSTED only on confirmed message id
                post_status, channel, message_id = "POSTED", result.get("channel"), str(result.get("message_id"))
                posted_at, dry_run = result.get("posted_at") or now_utc(), False
            else:
                post_status, channel = "FAILED", result.get("channel")

    receipt = _write_receipt(post_status=post_status, brief_sha256=brief_sha, scan_run_id=scan_run_id,
                             posted_at=posted_at, channel=channel, message_id=message_id, dry_run=dry_run, **counts)
    incomplete = mode in ("chat", "both") and post_status == "FAILED"
    ok = post_status in ("FILE_ONLY", "CHAT_UNAVAILABLE", "POSTED")
    return {
        "status": "POSTED" if post_status == "POSTED" else ("INCOMPLETE" if incomplete else "READY"),
        "post_status": post_status,
        "ok": ok,
        "brief_sha256": brief_sha,
        "scan_run_id": scan_run_id,
        "has_doc_only_warnings": has_doc_only_warnings,
        "defined_not_built_count": defined_not_built,
        "blocked_count": blocked,
        "sealed_count": sealed,
        "modified_product_state": False,
        "wrote_release_ready": False,
        "model_wiring_performed": False,
        "receipt": receipt,
        "output_root": rel(root, out_dir),
    }
