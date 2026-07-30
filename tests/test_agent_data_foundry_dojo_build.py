from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent_data_foundry_test_helpers import (
    _DOJO_DIR,
    _REALISH_GH_TOKEN,
    _SAMPLE_DIFF,
    _signals,
    _write_dojo_gold,
)

from agent_data_foundry import (
    SIGNAL_COVERAGE_FAMILIES,
    build_inhouse_dojo,
    main,
    source_signal_safety_report,
    validate_data_need,
    validate_data_rights,
)


def test_build_inhouse_dojo_emits_internal_only_graded_dataset(tmp_path: Path) -> None:
    _write_dojo_gold(tmp_path)

    result = build_inhouse_dojo(tmp_path)

    assert result["status"] == "INHOUSE_READY"
    assert result["rows_seen"] == 3
    assert result["rows_emitted"] == 2  # quarantine excluded
    assert result["rows_rejected"] == 1
    assert result["external_release_allowed"] is False
    assert result["commercial_sale_allowed"] is False

    dojo = tmp_path / _DOJO_DIR
    rows = [json.loads(line) for line in (dojo / "factory_dojo_internal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    ids = {r["fingerprint"] for r in rows}
    assert ids == {"fp-internal", "fp-critical"}
    assert "fp-quarantine" not in ids

    for row in rows:
        assert row.get("data_need")
        assert row.get("data_rights")
        assert row.get("model_origin")
        assert validate_data_need(row["data_need"]) == []
        assert validate_data_rights(row["data_rights"]) == []
        assert row["data_rights"]["export_allowed"] is False
        assert row["data_rights"]["commercial_sale_allowed"] is False
        assert row["data_rights"]["grade"] != "F_QUARANTINE"

    # The CRITICAL-value row is retained, internal-only.
    critical = next(r for r in rows if r["fingerprint"] == "fp-critical")
    assert critical["data_need"]["technical_value"] == "CRITICAL"
    assert critical["data_rights"]["export_allowed"] is False


def test_build_inhouse_dojo_never_writes_release_ready(tmp_path: Path) -> None:
    _write_dojo_gold(tmp_path)
    build_inhouse_dojo(tmp_path)
    # The internal Dojo lane must not create or touch the external release tree.
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()
    assert (tmp_path / _DOJO_DIR / "factory_dojo_internal.jsonl").exists()


def test_build_inhouse_dojo_manifest_and_reports(tmp_path: Path) -> None:
    _write_dojo_gold(tmp_path)
    build_inhouse_dojo(tmp_path)
    dojo = tmp_path / _DOJO_DIR

    manifest = json.loads((dojo / "factory_dojo_manifest.json").read_text(encoding="utf-8"))
    assert manifest["dataset_id"] == "factory-dojo-internal"
    assert manifest["status"] == "INHOUSE_READY"
    assert manifest["record_count"] == 2
    assert manifest["external_release_allowed"] is False
    assert manifest["commercial_sale_allowed"] is False
    assert manifest["technical_value_counts"].get("CRITICAL") == 1

    rights = json.loads((dojo / "factory_dojo_rights_report.json").read_text(encoding="utf-8"))
    assert rights["export_allowed_rows"] == 0
    assert rights["commercial_sale_rows"] == 0
    assert rights["quarantine_rows"] == 0
    assert rights["all_internal_only"] is True

    quality = json.loads((dojo / "factory_dojo_quality_report.json").read_text(encoding="utf-8"))
    assert quality["rows_seen"] == 3
    assert quality["rows_emitted"] == 2
    assert quality["rows_rejected"] == 1


def test_dojo_rejection_detail_is_complete_and_hashed(tmp_path: Path) -> None:
    gold = (
        tmp_path
        / "data"
        / "training-library"
        / "10_working"
        / "coordination-harvest"
        / "20_gold"
        / "product_incidents.jsonl"
    )
    gold.parent.mkdir(parents=True)
    rows = [
        {
            "incident_type": "SUPPORTED_CLAIM",
            "fingerprint": f"quarantine-{index}",
            "commercial_safety": {"contains_secrets": True},
        }
        for index in range(60)
    ]
    gold.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    build_inhouse_dojo(tmp_path)
    dojo = tmp_path / _DOJO_DIR
    report = json.loads((dojo / "factory_dojo_quality_report.json").read_text(encoding="utf-8"))
    rejection_path = tmp_path / report["rejections_path"]
    assert report["rows_rejected"] == 60
    assert len(report["rejections"]) == 50
    assert report["rejections_complete"] is False
    assert len(rejection_path.read_text(encoding="utf-8").splitlines()) == 60
    assert report["rejections_sha256"] == hashlib.sha256(rejection_path.read_bytes()).hexdigest()


def test_cli_build_inhouse_dojo_action(tmp_path: Path, capsys) -> None:
    _write_dojo_gold(tmp_path)
    exit_code = main(["--action", "build-inhouse-dojo", "--root", str(tmp_path)])

    assert exit_code == 0
    assert "Factory Dojo internal export" in capsys.readouterr().out
    assert (tmp_path / _DOJO_DIR / "factory_dojo_manifest.json").exists()


def test_build_inhouse_dojo_action_registered_in_public_cli(tmp_path: Path, capsys) -> None:
    _write_dojo_gold(tmp_path)
    assert main(["--action", "build-inhouse-dojo", "--root", str(tmp_path)]) == 0
    assert "Factory Dojo internal export" in capsys.readouterr().out


def test_build_inhouse_dojo_adds_signal_coverage_and_report(tmp_path: Path) -> None:
    _write_dojo_gold(tmp_path)
    build_inhouse_dojo(tmp_path)
    dojo = tmp_path / _DOJO_DIR

    rows = [json.loads(line) for line in (dojo / "factory_dojo_internal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows
    for row in rows:
        assert row.get("signal_coverage")
        assert set(row["signal_coverage"]["families"]) == set(SIGNAL_COVERAGE_FAMILIES)

    report = json.loads((dojo / "factory_dojo_signal_coverage_report.json").read_text(encoding="utf-8"))
    assert report["schema_version"] == "sf.factory_dojo.signal_coverage_report.v0.1"
    assert report["records_with_signal_coverage"] == len(rows)
    assert "claim_target_alignment" in report["family_status_counts"]
    assert report["overall_signal_value_counts"]["CRITICAL"] >= 1  # MISDIRECTED_VERIFICATION row
    assert len(report["recommended_next_instrumentation"]) == 3

    # No external release tree was written.
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()


def test_build_inhouse_dojo_attaches_diff_test_integrity(tmp_path: Path) -> None:
    _write_dojo_gold(tmp_path)
    build_inhouse_dojo(tmp_path)
    rows = [json.loads(line) for line in (tmp_path / _DOJO_DIR / "factory_dojo_internal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows
    for row in rows:
        block = row.get("diff_test_integrity")
        assert block and block["schema_version"] == "sf.diff_test_integrity.v0.3"
        assert "assertion_delta" in block and "mock_skip_signals" in block
        assert "file_op_types" in block and "test_signal" in block and "protected_signal" in block
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()


def test_build_inhouse_dojo_quarantines_and_redacts(tmp_path: Path) -> None:
    gold = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    gold.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"incident_type": "CLAIM_WITHOUT_EVIDENCE", "fingerprint": "fp-clean", "verdict": "BLOCK", "agent": "codex",
         "source_signals": _signals(paths_touched=["src/a.py"], commands_run=["pytest -q"])},
        {"incident_type": "CLAIM_WITHOUT_EVIDENCE", "fingerprint": "fp-secret", "verdict": "BLOCK", "agent": "codex",
         "source_signals": _signals(commands_run=[f"deploy --token={_REALISH_GH_TOKEN}"])},
        {"incident_type": "CLAIM_WITHOUT_EVIDENCE", "fingerprint": "fp-redact", "verdict": "BLOCK", "agent": "codex",
         "source_signals": _signals(paths_touched=[r"C:/Users/sample-user/notes.py"], commands_run=["echo me@example.com"])},
    ]
    gold.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    build_inhouse_dojo(tmp_path)
    dojo = tmp_path / _DOJO_DIR
    emitted = [json.loads(line) for line in (dojo / "factory_dojo_internal.jsonl").read_text(encoding="utf-8").splitlines()]
    fingerprints = {r.get("fingerprint") for r in emitted}
    # The secret-bearing row is quarantined out; clean and redacted survive.
    assert "fp-secret" not in fingerprints
    assert {"fp-clean", "fp-redact"}.issubset(fingerprints)

    redact_row = next(r for r in emitted if r["fingerprint"] == "fp-redact")
    assert redact_row["source_signal_safety"]["scan_status"] == "REDACTED"
    assert "sample-user" not in json.dumps(redact_row["source_signals"])
    assert "me@example.com" not in json.dumps(redact_row["source_signals"])

    clean_row = next(r for r in emitted if r["fingerprint"] == "fp-clean")
    assert clean_row["source_signal_safety"]["scan_status"] == "PASS"

    # Build-time report sees the full scan including the quarantined row.
    safety_report = json.loads((dojo / "factory_dojo_source_signal_safety_report.json").read_text(encoding="utf-8"))
    assert safety_report["scope"] == "full_scan_including_quarantined"
    assert safety_report["status_counts"]["QUARANTINE"] == 1
    assert safety_report["quarantined_rows"] == 1
    assert safety_report["all_clear"] is False

    # Survivor-view re-derivation never shows a quarantined survivor.
    survivor = source_signal_safety_report(tmp_path)
    assert survivor["scope"] == "emitted_survivors_only"
    assert survivor["status_counts"]["QUARANTINE"] == 0
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()


def test_source_signals_feed_diff_test_capture_in_dojo(tmp_path: Path) -> None:
    gold = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    gold.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "incident_type": "CLAIM_WITHOUT_EVIDENCE", "fingerprint": "fp-sig", "verdict": "BLOCK", "agent": "codex",
        "quality": {"passed": True},
        "source_signals": {
            "schema_version": "sf.source_signals.v0.1",
            "paths_touched": ["src/demo.py", "tests/test_demo.py"],
            "changed_file_count": 2,
            "commands_run": ["pytest tests/test_demo.py"],
            "command_surfaces": ["pytest"], "command_exit_codes": [],
            "test_commands": ["pytest tests/test_demo.py"], "test_command_present": True,
            "test_files_touched": ["tests/test_demo.py"], "protected_path_touches": ["tests/test_demo.py"],
        },
    }
    gold.write_text(json.dumps(row) + "\n", encoding="utf-8")
    build_inhouse_dojo(tmp_path)
    rows = [json.loads(line) for line in (tmp_path / _DOJO_DIR / "factory_dojo_internal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows
    block = rows[0]["diff_test_integrity"]
    assert block["diff_stat"]["files_changed"] == 2  # sourced from source_signals, not top-level
    assert any("test_demo.py" in p for p in block["test_files_changed"])
    assert "pytest" in block["test_command"]
    assert block["test_exit_code"] == 0
    fam = rows[0]["signal_coverage"]["families"]["diff_test_integrity"]
    assert fam["status"] == "partial"  # capture lifts the family off missing for future rows
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()


def test_dojo_attaches_tool_call_trajectory(tmp_path: Path) -> None:
    gold = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    gold.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "incident_type": "CLAIM_WITHOUT_EVIDENCE", "fingerprint": "fp-tool", "verdict": "BLOCK", "agent": "codex",
        "source_signals": _signals(commands_run=["pytest -q", "git push"]),
    }
    gold.write_text(json.dumps(row) + "\n", encoding="utf-8")
    build_inhouse_dojo(tmp_path)
    rows = [json.loads(line) for line in (tmp_path / _DOJO_DIR / "factory_dojo_internal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows
    block = rows[0]["tool_call_trajectory"]
    assert block["schema_version"] == "sf.tool_call_trajectory.v0.1"
    assert block["trajectory_source"] == "command_receipt"
    assert block["tool_sequence"] == ["pytest", "git"]
    assert rows[0]["signal_coverage"]["families"]["tool_call_trajectory"]["status"] == "partial"
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()


def test_dojo_attaches_human_correction_lineage(tmp_path: Path) -> None:
    gold = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    gold.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "incident_type": "CLAIM_WITHOUT_EVIDENCE", "fingerprint": "fp-corr", "verdict": "BLOCK", "agent": "codex",
        "claim_evidence_alignment": {"evidence_contradicts_claim": True, "contradiction_type": "CLAIM_WITHOUT_EVIDENCE"},
        "gold_output": {"verdict": "BLOCK", "required_action": "REJECT_PROMOTION", "model_should_learn": "Cite evidence."},
        "state_transition": {"artifact_state_approved": "NEEDS_REVIEW", "promotion_allowed": False},
    }
    gold.write_text(json.dumps(row) + "\n", encoding="utf-8")
    build_inhouse_dojo(tmp_path)
    rows = [json.loads(line) for line in (tmp_path / _DOJO_DIR / "factory_dojo_internal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows
    block = rows[0]["human_correction_lineage"]
    assert block["schema_version"] == "sf.human_correction_lineage.v0.1"
    assert block["correction_source"] == "machine_adjudication"
    assert rows[0]["signal_coverage"]["families"]["human_correction_lineage"]["status"] == "partial"
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()


def test_dojo_attaches_model_route_cost(tmp_path: Path) -> None:
    gold = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    gold.parent.mkdir(parents=True, exist_ok=True)
    row = {"incident_type": "CLAIM_WITHOUT_EVIDENCE", "fingerprint": "fp-mrc", "verdict": "BLOCK", "agent": "claude"}
    gold.write_text(json.dumps(row) + "\n", encoding="utf-8")
    build_inhouse_dojo(tmp_path)
    rows = [json.loads(line) for line in (tmp_path / _DOJO_DIR / "factory_dojo_internal.jsonl").read_text(encoding="utf-8").splitlines()]
    assert rows
    block = rows[0]["model_route_cost"]
    assert block["schema_version"] == "sf.model_route_cost.v0.1"
    assert block["provider"] == "anthropic"  # from model_origin (agent=claude)
    assert block["model_name"] is None  # never the agent name
    assert block["cost_source"] == "model_origin"
    assert rows[0]["signal_coverage"]["families"]["model_route_cost"]["status"] == "partial"
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()


def test_dojo_consumes_diff_then_strips_it(tmp_path: Path) -> None:
    gold = tmp_path / "data" / "training-library" / "10_working" / "coordination-harvest" / "20_gold" / "product_incidents.jsonl"
    gold.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        # Diff text with assertions/mocks -> counts derived, then patch stripped.
        {"incident_type": "CLAIM_WITHOUT_EVIDENCE", "fingerprint": "fp-diff", "verdict": "BLOCK", "agent": "codex",
         "source_signals": _signals(paths_touched=["tests/test_x.py"], file_status=[{"op": "modified", "path": "tests/test_x.py"}], diff_patch=_SAMPLE_DIFF)},
        # Severe secret literal in the patch -> quarantined out.
        {"incident_type": "CLAIM_WITHOUT_EVIDENCE", "fingerprint": "fp-secret-diff", "verdict": "BLOCK", "agent": "codex",
         "source_signals": _signals(diff_patch=f'+    TOKEN = "{_REALISH_GH_TOKEN}"\n')},
    ]
    gold.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")

    build_inhouse_dojo(tmp_path)
    dojo = tmp_path / _DOJO_DIR
    emitted = [json.loads(line) for line in (dojo / "factory_dojo_internal.jsonl").read_text(encoding="utf-8").splitlines()]
    fps = {r["fingerprint"] for r in emitted}
    assert "fp-secret-diff" not in fps  # quarantined
    assert "fp-diff" in fps

    diff_row = next(r for r in emitted if r["fingerprint"] == "fp-diff")
    block = diff_row["diff_test_integrity"]
    # Derived counts persist...
    assert block["assertion_delta"]["assertions_added"] == 2
    assert block["mock_skip_signals"]["mocks_added"] == 1
    assert block["file_op_types"] == {"created": 0, "modified": 1, "deleted": 0, "renamed": 0, "unknown": 0}
    # ...but the raw patch text never survives into the training row.
    assert "diff_patch" not in diff_row.get("source_signals", {})
    assert "diff_patch" not in diff_row
    assert "raw patch" not in json.dumps(diff_row) and "assert old_value" not in json.dumps(diff_row)
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()
