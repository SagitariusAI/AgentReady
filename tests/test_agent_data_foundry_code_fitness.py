from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agent_data_foundry import (
    code_fitness_scan,
)

_CF_REPORTS = ("code_fitness_report.json", "code_structure_report.json", "debug_receipt_gap_report.json",
               "file_split_report.json", "comment_docstring_report.json",
               "optional_scanner_availability_report.json", "hardware_overhead_risk_report.json")


def _cf_fixture(tmp_path: Path) -> list[str]:
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "big900.py").write_text("x = 1\n" * 920, encoding="utf-8")
    (tmp_path / "src" / "big600.py").write_text("y = 1\n" * 650, encoding="utf-8")
    (tmp_path / "src" / "swallow.py").write_text(
        "def do():\n    return 1\n\n\ndef run():\n    try:\n        do()\n    except Exception:\n        pass\n", encoding="utf-8")
    (tmp_path / ".agentready").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".agentready" / "gate_status.json").write_text(json.dumps({"status": "pass", "ref": "deadbeef"}), encoding="utf-8")
    return [str(tmp_path / "src" / n) for n in ("big900.py", "big600.py", "swallow.py")]


def _run_cf(tmp_path: Path):
    paths = _cf_fixture(tmp_path)
    out = tmp_path / "out"
    result = code_fitness_scan(tmp_path, paths=paths, output_path=out, run_lint=False)
    report = json.loads((out / "code_fitness_report.json").read_text(encoding="utf-8"))
    return result, report, out, paths


def test_code_fitness_emits_all_reports(tmp_path: Path) -> None:
    result, report, out, _paths = _run_cf(tmp_path)
    for name in _CF_REPORTS:
        assert (out / name).exists()
    block = report["code_fitness"]
    required = {"schema_version", "lint_clean", "tests_passed", "debug_receipt_present", "structure_ok",
                "comments_ok", "file_split_ok", "security_scan_ok", "runtime_evidence_ok", "serviceability_ok",
                "hardware_overhead_reviewed", "score", "blocking_findings", "warnings"}
    assert required <= set(block) and block["score"] in ("PASS", "WARN", "BLOCK")
    assert block["schema_version"] == "sf.code_fitness.v0.1"
    assert result["mode"] == "report_only" and result["no_mutation"] is True


def test_code_fitness_flags_large_files(tmp_path: Path) -> None:
    _result, report, _out, _paths = _run_cf(tmp_path)
    msgs = [f["message"] for f in report["findings"]]
    assert any("big900.py" in m and ">900" in m for m in msgs)  # BLOCK
    assert any("big600.py" in m and ">600" in m for m in msgs)  # WARN
    assert report["code_fitness"]["score"] == "BLOCK" and report["code_fitness"]["structure_ok"] is False


def test_code_fitness_flags_broad_except_pass(tmp_path: Path) -> None:
    _result, report, _out, _paths = _run_cf(tmp_path)
    svc = [f for f in report["findings"] if f["category"] == "serviceability" and f["severity"] == "WARN"]
    assert any("swallowed failure" in f["message"] for f in svc)


def test_code_fitness_records_scanner_availability(tmp_path: Path) -> None:
    _result, _report, out, _paths = _run_cf(tmp_path)
    tools = json.loads((out / "optional_scanner_availability_report.json").read_text(encoding="utf-8"))["tools"]
    assert set(tools) == {"ruff", "gitleaks", "bandit", "pip-audit", "semgrep"}
    assert all(v in ("available", "not_available") for v in tools.values())


def test_code_fitness_findings_have_curriculum_fields(tmp_path: Path) -> None:
    _result, report, _out, _paths = _run_cf(tmp_path)
    assert report["findings"]
    for f in report["findings"]:
        assert {"curriculum_family", "sign", "anchor", "repair_target"} <= set(f)
        assert f["sign"] in ("+", "-")


def test_code_fitness_gate_marker_detected(tmp_path: Path) -> None:
    _result, report, _out, _paths = _run_cf(tmp_path)
    assert report["git_gate_state"]["gate_status"] == "pass" and report["git_gate_state"]["gate_ref"] == "deadbeef"


def test_code_fitness_no_mutation_no_release_ready(tmp_path: Path) -> None:
    paths = _cf_fixture(tmp_path)
    before = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
    result = code_fitness_scan(tmp_path, paths=paths, output_path=tmp_path / "out", run_lint=False)
    after = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in paths}
    assert before == after  # no code mutation
    assert result["wrote_release_ready"] is False
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()
