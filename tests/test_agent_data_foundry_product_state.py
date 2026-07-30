from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent_data_foundry_test_helpers import (
    _REALISH_GH_TOKEN,
)

from agent_data_foundry import (
    _classify_product_status,
    product_reality_brief_post,
    product_state_scan,
)

_PS_SPECS = [
    {"component_id": "x.doc", "component_name": "Doc only", "subsystem": "s", "kind": "doc", "docs": ["docs/SPEC.md"]},
    {"component_id": "x.plan", "component_name": "Plan only", "subsystem": "s", "kind": "plan", "docs": ["docs/PLAN.md"]},
    {"component_id": "x.built", "component_name": "Built", "subsystem": "s", "kind": "code", "code": [("src/mymod.py", "my_func")]},
    {"component_id": "x.tested", "component_name": "Tested", "subsystem": "s", "kind": "code", "code": [("src/mymod.py", "my_func")], "tests": ["test_marker_one"]},
    {"component_id": "x.sealed", "component_name": "Sealed", "subsystem": "s", "kind": "doc", "docs": ["docs/SEALED.md"]},
]


def _ps_write(tmp_path: Path, rel: str, content: str) -> None:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _ps_fixture_repo(tmp_path: Path) -> None:
    _ps_write(tmp_path, "src/mymod.py", "def my_func():\n    return 1\n")
    _ps_write(tmp_path, "tests/test_x.py", "def test_marker_one():\n    assert True\n")
    _ps_write(tmp_path, ".agentready/gate_status.json", json.dumps({"status": "pass", "ref": "abc123"}))
    _ps_write(tmp_path, "docs/SPEC.md", "---\ntitle: Spec\n---\n# Spec\n")
    _ps_write(tmp_path, "docs/PLAN.md", "---\ntitle: Plan\n---\n# Plan\n")
    _ps_write(tmp_path, "docs/SEALED.md", "---\ntitle: Sealed\nstatus: sealed\n---\n# Sealed\n")


def _run_ps_scan(tmp_path: Path):
    _ps_fixture_repo(tmp_path)
    out = tmp_path / "out"
    result = product_state_scan(tmp_path, components=_PS_SPECS, output_path=out)
    draft = json.loads((out / "product_state_ledger_draft.json").read_text(encoding="utf-8"))
    by_id = {c["component_id"]: c for c in draft["components"]}
    return result, draft, by_id, out


def _result_schema_valid(tmp_path: Path) -> bool:
    result = product_state_scan(tmp_path, components=_PS_SPECS, output_path=tmp_path / "out")
    return bool(result["schema_valid"]) and not result["schema_errors"]


def _gen_brief(tmp_path: Path) -> Path:
    _ps_fixture_repo(tmp_path)
    out = tmp_path / "out"
    product_state_scan(tmp_path, components=_PS_SPECS, output_path=out)
    return out


def _post_receipt(out: Path) -> dict:
    return json.loads((out / "product_reality_brief_post_receipt.json").read_text(encoding="utf-8"))


def test_classify_product_status_bar() -> None:
    # a well-defined document is not proof of implementation
    assert _classify_product_status({"DOC_DEFINED_ONLY"}, "doc") == "DEFINED"
    assert _classify_product_status({"DOC_DEFINED_ONLY"}, "plan") == "PLANNED"
    # code + gate receipt -> BUILT; + tests -> TESTED
    assert _classify_product_status({"CODE_EXISTS", "GATE_GREEN"}, "code") == "BUILT"
    assert _classify_product_status({"CODE_EXISTS", "TEST_EXISTS", "GATE_GREEN"}, "code") == "TESTED"
    assert _classify_product_status({"CODE_EXISTS"}, "code") == "IN_PROGRESS"
    assert _classify_product_status({"SEALED", "DOC_DEFINED_ONLY"}, "doc") == "SEALED"
    # docs alone NEVER reach BUILT
    assert _classify_product_status({"DOC_DEFINED_ONLY"}, "doc") != "BUILT"


def test_product_state_scan_status_bar(tmp_path: Path) -> None:
    _result, _draft, by_id, _out = _run_ps_scan(tmp_path)
    assert by_id["x.doc"]["status"] == "DEFINED" and "DOC_DEFINED_ONLY" in by_id["x.doc"]["evidence_tags"]
    assert by_id["x.doc"]["status"] != "BUILT"  # doc-only never BUILT
    assert by_id["x.plan"]["status"] == "PLANNED"
    assert by_id["x.built"]["status"] == "BUILT"  # code + gate receipt
    assert by_id["x.tested"]["status"] == "TESTED"  # gate receipt lifts to TESTED
    assert by_id["x.sealed"]["status"] == "SEALED"  # sealed stays SEALED


def test_product_state_scan_release_ready_is_not_sell_ready(tmp_path: Path) -> None:
    _result, draft, _by_id, out = _run_ps_scan(tmp_path)
    for c in draft["components"]:
        assert c["status"] not in ("RELEASE_CANDIDATE", "PRODUCTION_READY")  # scanner never infers these
        assert c["commercial_clearance"] != "cleared"  # never claims commercial clearance
        assert c["founder_acceptance"] is None  # never fabricated
    brief = (out / "product_reality_brief.md").read_text(encoding="utf-8").lower()
    assert "not asserted here" in brief and "sell-ready" in brief  # brief separates sell-ready explicitly


def test_product_state_scan_gap_report_and_outputs(tmp_path: Path) -> None:
    result, _draft, _by_id, out = _run_ps_scan(tmp_path)
    for name in ("product_state_ledger_draft.json", "product_reality_brief.md",
                 "product_state_evidence_report.json", "product_state_gap_report.json"):
        assert (out / name).exists()
    gaps = json.loads((out / "product_state_gap_report.json").read_text(encoding="utf-8"))["gaps"]
    gap_ids = {g["component_id"] for g in gaps}
    assert "x.doc" in gap_ids  # doc-only has missing implementation evidence
    assert result["mode"] == "dry_run" and result["model_wiring_performed"] is False


def test_product_state_scan_validates_against_schema(tmp_path: Path) -> None:
    import agent_data_foundry as adf
    _result, draft, _by_id, _out = _run_ps_scan(tmp_path)
    schema_path = Path(adf.__file__).resolve().parents[1] / "docs" / "product_state" / "product_state_ledger.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    try:
        import jsonschema
        jsonschema.validate(draft, schema)
    except ImportError:
        req = set(schema["definitions"]["component"]["required"])
        for c in draft["components"]:
            assert req <= set(c) and c["status"] in schema["definitions"]["status"]["enum"]
    assert _result_schema_valid(tmp_path)


def test_product_state_scan_no_release_ready_writes(tmp_path: Path) -> None:
    _run_ps_scan(tmp_path)
    result = product_state_scan(tmp_path, components=_PS_SPECS, output_path=tmp_path / "out")
    assert result["wrote_release_ready"] is False
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()


def test_brief_post_file_mode_receipt(tmp_path: Path) -> None:
    out = _gen_brief(tmp_path)
    result = product_reality_brief_post(tmp_path, brief_mode="file", output_path=out)
    assert result["post_status"] == "FILE_ONLY" and result["ok"] is True
    rec = _post_receipt(out)
    assert rec["schema_version"] == "sf.product_reality_brief_post.v0.1" and rec["dry_run"] is True
    assert rec["brief_sha256"] and rec["message_id"] is None
    assert not (out / "product_reality_brief_post_ready.md").exists()  # no chat artifact in file mode


def test_brief_post_chat_unavailable_not_fake_posted(tmp_path: Path) -> None:
    out = _gen_brief(tmp_path)
    result = product_reality_brief_post(tmp_path, brief_mode="chat", chat_poster=None, output_path=out)
    assert result["post_status"] == "CHAT_UNAVAILABLE" and result["ok"] is True
    rec = _post_receipt(out)
    assert rec["post_status"] == "CHAT_UNAVAILABLE" and rec["message_id"] is None and rec["dry_run"] is True
    assert (out / "product_reality_brief_post_ready.md").exists()  # post-ready artifact emitted


def test_brief_post_posted_requires_confirmation(tmp_path: Path) -> None:
    out = _gen_brief(tmp_path)

    def confirmed(_text: str) -> dict:
        return {"ok": True, "message_id": "msg-1", "channel": "#dev-command", "posted_at": "2026-06-16T00:00:00Z"}

    def unconfirmed(_text: str) -> dict:
        return {"ok": True}  # no message_id -> not a confirmed post

    posted = product_reality_brief_post(tmp_path, brief_mode="chat", chat_poster=confirmed, output_path=out)
    assert posted["post_status"] == "POSTED" and _post_receipt(out)["message_id"] == "msg-1"
    assert _post_receipt(out)["dry_run"] is False and _post_receipt(out)["channel"] == "#dev-command"

    failed = product_reality_brief_post(tmp_path, brief_mode="chat", chat_poster=unconfirmed, output_path=out)
    assert failed["post_status"] == "FAILED" and failed["ok"] is False  # never POSTED without confirmation


def test_brief_post_missing_brief_fails_safely(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir(parents=True)
    result = product_reality_brief_post(tmp_path, brief_mode="chat", chat_poster=None, output_path=out)
    assert result["post_status"] == "MISSING_BRIEF" and result["ok"] is False
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()


def test_brief_post_receipt_includes_brief_hash(tmp_path: Path) -> None:
    out = _gen_brief(tmp_path)
    product_reality_brief_post(tmp_path, brief_mode="file", output_path=out)
    brief = (out / "product_reality_brief.md").read_text(encoding="utf-8")
    assert _post_receipt(out)["brief_sha256"] == hashlib.sha256(brief.encode("utf-8")).hexdigest()


def test_brief_post_does_not_modify_product_state(tmp_path: Path) -> None:
    out = _gen_brief(tmp_path)
    before = (out / "product_state_ledger_draft.json").read_bytes()
    product_reality_brief_post(tmp_path, brief_mode="both",
                               chat_poster=lambda _t: {"ok": True, "message_id": "m9"}, output_path=out)
    after = (out / "product_state_ledger_draft.json").read_bytes()
    assert before == after  # posting never mutates product state
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()


def test_brief_post_secret_blocked(tmp_path: Path) -> None:
    out = _gen_brief(tmp_path)
    # a brief that somehow contains a real-looking secret must never be posted
    (out / "product_reality_brief.md").write_text(f"# Brief\nleaked token {_REALISH_GH_TOKEN}\n", encoding="utf-8")
    result = product_reality_brief_post(tmp_path, brief_mode="chat",
                                        chat_poster=lambda _t: {"ok": True, "message_id": "m"}, output_path=out)
    assert result["post_status"] == "SECRET_BLOCKED" and result["ok"] is False
    assert not (out / "product_reality_brief_post_ready.md").exists()
