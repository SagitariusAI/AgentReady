# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json

from agent_data_foundry_lib.product_state import (
    _PS_EVIDENCE_TAGS,
    _PS_STATUSES,
    PRODUCT_STATE_LEDGER_SCHEMA_VERSION,
    _classify_product_status,
    _validate_ledger_draft,
    product_reality_brief_post,
    product_state_root,
    product_state_scan,
)

# A small in-test component registry: a doc-only spec (DEFINED), a code+gate spec
# (BUILT/TESTED depending on gate), kept independent of the real product registry.
_PS_SPECS = [
    {"component_id": "demo.doc_only", "component_name": "Doc Only Thing", "subsystem": "x", "kind": "doc",
     "docs": ["docs/DEMO.md"]},
    {"component_id": "demo.coded", "component_name": "Coded Thing", "subsystem": "x", "kind": "code",
     "code": [("src/demo_mod.py", "demo_fn")], "tests": ["test_demo_fn"]},
]


def _seed(root):
    (root / "docs").mkdir(parents=True, exist_ok=True)
    (root / "docs" / "DEMO.md").write_text("# Demo\nA spec.\n", encoding="utf-8")
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "demo_mod.py").write_text("def demo_fn():\n    return 1\n", encoding="utf-8")
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "test_demo.py").write_text("def test_demo_fn():\n    assert True\n", encoding="utf-8")


def _set_gate(root, status):
    gate = root / ".agentready"
    gate.mkdir(parents=True, exist_ok=True)
    (gate / "gate_status.json").write_text(json.dumps({"status": status}), encoding="utf-8")


def test_classify_status_bar_doc_never_built():
    # A well-defined document is not proof of implementation.
    assert _classify_product_status({"DOC_DEFINED_ONLY"}, "doc") == "DEFINED"
    assert _classify_product_status({"DOC_DEFINED_ONLY"}, "plan") == "PLANNED"
    assert _classify_product_status({"DOC_DEFINED_ONLY"}, "doc") != "BUILT"
    assert _classify_product_status({"CODE_EXISTS", "GATE_GREEN"}, "code") == "BUILT"
    assert _classify_product_status({"CODE_EXISTS", "TEST_EXISTS", "GATE_GREEN"}, "code") == "TESTED"
    assert _classify_product_status({"CODE_EXISTS"}, "code") == "IN_PROGRESS"
    assert _classify_product_status({"SEALED", "DOC_DEFINED_ONLY"}, "doc") == "SEALED"
    # RELEASE_CANDIDATE / PRODUCTION_READY are never inferred
    assert _classify_product_status({"CODE_EXISTS", "TEST_EXISTS", "GATE_GREEN", "PACKAGED"}, "code") == "TESTED"


def test_scan_outputs_schema_and_dry_run(tmp_path):
    _seed(tmp_path)
    _set_gate(tmp_path, "pass")
    out = tmp_path / "out"
    result = product_state_scan(tmp_path, components=_PS_SPECS, output_path=out)
    assert result["status"] == "SCANNED" and result["mode"] == "dry_run"
    assert result["model_wiring_performed"] is False and result["wrote_release_ready"] is False
    for name in ("product_state_ledger_draft.json", "product_reality_brief.md",
                 "product_state_evidence_report.json", "product_state_gap_report.json"):
        assert (out / name).exists(), name
    draft = json.loads((out / "product_state_ledger_draft.json").read_text(encoding="utf-8"))
    assert draft["schema_version"] == PRODUCT_STATE_LEDGER_SCHEMA_VERSION
    ok, errors = _validate_ledger_draft(draft)
    assert ok and errors == [] and result["schema_valid"] is True
    statuses = {c["component_id"]: c["status"] for c in draft["components"]}
    assert statuses["demo.doc_only"] == "DEFINED"  # doc -> DEFINED, never BUILT
    assert statuses["demo.coded"] == "TESTED"  # code + test + gate green
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()


def test_no_status_upgrade_without_gate(tmp_path):
    _seed(tmp_path)
    _set_gate(tmp_path, "fail")  # gate not green
    out = tmp_path / "out"
    product_state_scan(tmp_path, components=_PS_SPECS, output_path=out)
    draft = json.loads((out / "product_state_ledger_draft.json").read_text(encoding="utf-8"))
    statuses = {c["component_id"]: c["status"] for c in draft["components"]}
    # no gate-green receipt -> code can only reach IN_PROGRESS, never BUILT/TESTED
    assert statuses["demo.coded"] == "IN_PROGRESS"


def test_brief_post_file_mode_receipt(tmp_path):
    _seed(tmp_path)
    _set_gate(tmp_path, "pass")
    out = tmp_path / "out"
    product_state_scan(tmp_path, components=_PS_SPECS, output_path=out)
    result = product_reality_brief_post(tmp_path, brief_mode="file", output_path=out)
    rec = result["receipt"]
    assert rec["schema_version"] == "sf.product_reality_brief_post.v0.1"
    assert rec["dry_run"] is True and rec["post_status"] == "FILE_ONLY"
    assert rec["modified_product_state"] is False and rec["wrote_release_ready"] is False
    assert result["ok"] is True


def test_chat_unavailable_is_not_posted(tmp_path):
    _seed(tmp_path)
    _set_gate(tmp_path, "pass")
    out = tmp_path / "out"
    product_state_scan(tmp_path, components=_PS_SPECS, output_path=out)
    result = product_reality_brief_post(tmp_path, brief_mode="chat", chat_poster=None, output_path=out)
    assert result["post_status"] == "CHAT_UNAVAILABLE"  # never a fake POSTED
    assert (out / "product_reality_brief_post_ready.md").exists()
    assert result["receipt"]["message_id"] is None


def test_posted_requires_confirmed_message_id(tmp_path):
    _seed(tmp_path)
    _set_gate(tmp_path, "pass")
    out = tmp_path / "out"
    product_state_scan(tmp_path, components=_PS_SPECS, output_path=out)
    confirmed = product_reality_brief_post(tmp_path, brief_mode="chat", output_path=out,
                                           chat_poster=lambda _t: {"ok": True, "message_id": "m1", "channel": "#dev"})
    assert confirmed["post_status"] == "POSTED" and confirmed["receipt"]["message_id"] == "m1"
    # a poster that does not confirm a message id is FAILED, never POSTED
    failed = product_reality_brief_post(tmp_path, brief_mode="chat", output_path=out,
                                        chat_poster=lambda _t: {"ok": True})
    assert failed["post_status"] == "FAILED"


def test_secret_in_brief_blocks_posting(tmp_path):
    _seed(tmp_path)
    _set_gate(tmp_path, "pass")
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    # a brief carrying a real-looking token must be SECRET_BLOCKED, not posted
    (out / "product_reality_brief.md").write_text(f"# Brief\nleaked {'ghp_' + 'ab' * 18}\n", encoding="utf-8")
    result = product_reality_brief_post(tmp_path, brief_mode="chat", output_path=out,
                                        chat_poster=lambda _t: {"ok": True, "message_id": "m"})
    assert result["post_status"] == "SECRET_BLOCKED" and result["ok"] is False
    assert not (out / "product_reality_brief_post_ready.md").exists()


def test_constants_and_root_and_reexport(tmp_path):
    assert "DEFINED" in _PS_STATUSES and "DOC_DEFINED_ONLY" in _PS_EVIDENCE_TAGS
    assert product_state_root(tmp_path).name == "product-state"
    import agent_data_foundry as adf
    assert adf.product_state_scan is product_state_scan
    assert adf.product_reality_brief_post is product_reality_brief_post
    assert adf._classify_product_status is _classify_product_status
