# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json

from agent_data_foundry_lib.code_fitness import (
    CODE_FITNESS_SCHEMA,
    _cf_tool_availability,
    code_fitness_scan,
)

_GODFILE = "x = 1\n" * 950  # > 900 lines -> BLOCK structure (god-file)
_LONGFN = "def big():\n" + "    a = 1\n" * 160 + "    return a\n"  # > 150 line function -> WARN
_TODO = "# TODO fix later\nx = 1\n"  # bare TODO -> WARN comments
_SWALLOW = "def f():\n    try:\n        pass\n    except Exception:\n        pass\n"  # broad except+pass -> WARN serviceability
_HEAVY = "import argparse\nimport numpy\ndef main():\n    pass\n"  # top-level heavy import on CLI path -> WARN hardware
_NODOC = "def public_fn():\n    return 1\n"  # public fn no docstring -> INFO comments


def _write(root, name, text):
    (root / name).write_text(text, encoding="utf-8")
    return name


def test_godfile_is_block_and_report_shape(tmp_path):
    p = _write(tmp_path, "godfile.py", _GODFILE)
    out = tmp_path / "out"
    result = code_fitness_scan(tmp_path, paths=[p], output_path=out, run_lint=False)
    assert result["status"] == "SCANNED" and result["mode"] == "report_only"
    assert result["no_mutation"] is True and result["wrote_release_ready"] is False
    assert result["score"] == "BLOCK" and result["severity_counts"]["BLOCK"] == 1
    # all 7 report files emitted
    for name in ("code_fitness_report.json", "code_structure_report.json", "file_split_report.json",
                 "comment_docstring_report.json", "debug_receipt_gap_report.json",
                 "optional_scanner_availability_report.json", "hardware_overhead_risk_report.json"):
        assert (out / name).exists(), name
    rep = json.loads((out / "code_fitness_report.json").read_text(encoding="utf-8"))
    assert rep["code_fitness"]["schema_version"] == CODE_FITNESS_SCHEMA
    block = rep["findings"][0]
    assert block["severity"] == "BLOCK" and block["category"] == "structure"
    # findings carry PairedCurriculum curriculum fields
    assert set(("curriculum_family", "sign", "anchor", "repair_target")) <= set(block)
    assert block["curriculum_family"] == "module_structure"


def test_finding_categories_and_severities(tmp_path):
    paths = [
        _write(tmp_path, "longfn.py", _LONGFN),
        _write(tmp_path, "todo.py", _TODO),
        _write(tmp_path, "swallow.py", _SWALLOW),
        _write(tmp_path, "heavy.py", _HEAVY),
        _write(tmp_path, "nodoc.py", _NODOC),
    ]
    out = tmp_path / "out"
    result = code_fitness_scan(tmp_path, paths=paths, output_path=out, run_lint=False)
    rep = json.loads((out / "code_fitness_report.json").read_text(encoding="utf-8"))
    cats = {(f["file"], f["category"], f["severity"]) for f in rep["findings"]}
    assert ("longfn.py", "structure", "WARN") in cats        # >150-line function
    assert ("todo.py", "comments", "WARN") in cats           # bare TODO
    assert ("swallow.py", "serviceability", "WARN") in cats  # broad except + pass
    assert ("heavy.py", "hardware", "WARN") in cats          # top-level heavy import on CLI path
    assert ("nodoc.py", "comments", "INFO") in cats          # public fn no docstring
    # no BLOCK among these -> score WARN
    assert result["score"] == "WARN" and result["severity_counts"]["BLOCK"] == 0


def test_optional_scanner_availability_recorded(tmp_path):
    p = _write(tmp_path, "clean.py", "def f():\n    '''ok.'''\n    return 1\n")
    out = tmp_path / "out"
    result = code_fitness_scan(tmp_path, paths=[p], output_path=out, run_lint=False)
    avail = json.loads((out / "optional_scanner_availability_report.json").read_text(encoding="utf-8"))
    # every optional scanner is recorded as available / not_available, never a failure
    for tool in ("ruff", "gitleaks", "bandit", "pip-audit", "semgrep"):
        assert avail["tools"][tool] in ("available", "not_available")
    assert "not a failure" in avail["note"]
    assert set(_cf_tool_availability()) == {"ruff", "gitleaks", "bandit", "pip-audit", "semgrep"}
    assert result["score"] == "PASS"  # a clean file with a docstring -> PASS


def test_report_only_no_release_ready_write(tmp_path):
    p = _write(tmp_path, "x.py", "x = 1\n")
    out = tmp_path / "out"
    code_fitness_scan(tmp_path, paths=[p], output_path=out, run_lint=False)
    assert not (tmp_path / "data" / "training-library" / "40_release_ready").exists()
    # source file is not mutated
    assert (tmp_path / "x.py").read_text(encoding="utf-8") == "x = 1\n"


def test_reexported_identity_from_agent_data_foundry():
    import agent_data_foundry as adf

    assert adf.code_fitness_scan is code_fitness_scan
