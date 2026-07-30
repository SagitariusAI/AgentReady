from __future__ import annotations

from pathlib import Path

from agent_data_foundry_lib.cerberus_release import (
    CERBERUS_RELEASE_ARTIFACTS,
    build_cerberus_release_gate,
    cerberus_checksums_gate,
    emit_cerberus_checksums,
    gate_item,
)
from agent_data_foundry_lib.paths import cerberus_release_root


def test_gate_item_shape():
    assert gate_item(True, "ok") == {"passed": True, "message": "ok"}
    assert gate_item(False, "no", {"x": 1}) == {"passed": False, "message": "no", "details": {"x": 1}}


def test_release_artifacts_list_stable():
    assert "dataset_card.md" in CERBERUS_RELEASE_ARTIFACTS
    assert "label_taxonomy.json" in CERBERUS_RELEASE_ARTIFACTS
    assert "split_manifest.json" in CERBERUS_RELEASE_ARTIFACTS


def test_release_gate_blocks_empty_corpus(tmp_path: Path):
    # an empty Gold corpus must NOT be release-ready
    result = build_cerberus_release_gate(tmp_path)
    assert result["schema_version"] == "agentready.data_foundry.release_gate.v1"
    assert result["status"] == "NOT_RELEASE_READY"
    assert result["gate"]["minimum_record_count_met"]["passed"] is False
    # the gate report + readme are written under 40_release_ready
    rr = cerberus_release_root(tmp_path)
    assert (rr / "release_gate_report.json").exists()
    assert (rr / "README.md").exists()


def test_checksums_gate_false_then_emit(tmp_path: Path):
    rr = cerberus_release_root(tmp_path)
    build_cerberus_release_gate(tmp_path)  # creates the scaffold
    assert cerberus_checksums_gate(rr)[0] is False  # not sealed yet
    out = emit_cerberus_checksums(tmp_path)
    assert "checksummed" in out and "release_status" in out
    assert (rr / "checksums" / "sha256sums.txt").exists()
    assert (rr / "release_receipt.json").exists()


def test_reexported_identity():
    import agent_data_foundry as adf
    import agent_data_foundry_lib as adfl

    assert adf.build_cerberus_release_gate is build_cerberus_release_gate
    assert adf.emit_cerberus_checksums is emit_cerberus_checksums
    assert adfl.build_cerberus_release_gate is build_cerberus_release_gate
