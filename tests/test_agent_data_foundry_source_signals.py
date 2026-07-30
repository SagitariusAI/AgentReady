from __future__ import annotations

import json

from agent_data_foundry_test_helpers import (
    _REALISH_GH_TOKEN,
    _SAMPLE_DIFF,
    _signals,
)

from agent_data_foundry import (
    SIGNAL_COVERAGE_FAMILIES,
    build_diff_test_integrity,
    build_signal_coverage,
    derive_assertion_delta,
    derive_file_op_types,
    derive_mock_skip_signals,
    extract_diff_text,
    gold_coordination_row,
    harvest_source_signals,
    normalize_git_file_status,
    receipt_gold_row,
    scan_source_signals,
    strip_diff_text_from_row,
)

_FIXTURE_DIFF = (
    "diff --git a/tests/test_auth.py b/tests/test_auth.py\n"
    "--- a/tests/test_auth.py\n"
    "+++ b/tests/test_auth.py\n"
    "@@ -1 +1,2 @@\n"
    '+    TOKEN = "ghp_FAKEexampletoken000000000000"\n'
    "+    assert client.authed is True\n"
)


def test_build_signal_coverage_returns_all_seven_families() -> None:
    cov = build_signal_coverage({"incident_type": "SUPPORTED_CLAIM"})
    assert set(cov["families"]) == set(SIGNAL_COVERAGE_FAMILIES)
    assert cov["schema_version"] == "sf.signal_coverage.v0.1"
    assert cov["coverage_source"] == "rapid_prototype"
    for info in cov["families"].values():
        assert info["status"] in ("present", "partial", "missing")
        assert isinstance(info["fields_present"], list)
        assert isinstance(info["fields_missing"], list)


def test_signal_coverage_marks_missing_not_fabricated() -> None:
    cov = build_signal_coverage({"incident_type": "SUPPORTED_CLAIM"})
    cta = cov["families"]["claim_target_alignment"]
    # Future fields are reported missing, never invented into fields_present.
    assert "claimed_repo" in cta["fields_missing"]
    assert "target_match" in cta["fields_missing"]
    assert "claimed_repo" not in cta["fields_present"]
    assert cta["status"] != "present"


def test_signal_coverage_partial_from_existing_evidence() -> None:
    record = {
        "incident_type": "CLAIM_WITHOUT_EVIDENCE",
        "repo": "D:/Demo", "commands_run": ["pytest"],
        "evidence": [{"path": "x"}], "paths_touched": ["a.py"],
    }
    cov = build_signal_coverage(record)
    cta = cov["families"]["claim_target_alignment"]
    assert cta["status"] == "partial"
    assert "repo" in cta["fields_present"]
    assert "commands_run" in cta["fields_present"]
    assert cov["families"]["diff_test_integrity"]["status"] == "partial"


def test_signal_coverage_critical_incident_raises_value() -> None:
    assert build_signal_coverage({"incident_type": "MISDIRECTED_VERIFICATION"})["overall_signal_value"] == "CRITICAL"
    # A no-signal, non-critical record is LOW.
    assert build_signal_coverage({"incident_type": "UNKNOWN_X"})["overall_signal_value"] == "LOW"


def test_build_diff_test_integrity_derives_bones_from_available_fields() -> None:
    record = {
        "incident_type": "CLAIM_WITHOUT_EVIDENCE",
        "paths_touched": [r"D:\Repo\src\demo.py", r"D:\Repo\tests\test_demo.py", r"D:\Repo\pyproject.toml"],
        "commands_run": ["ruff check src", "pytest tests/test_demo.py"],
        "quality": {"passed": True},
    }
    block = build_diff_test_integrity(record)
    assert block["schema_version"] == "sf.diff_test_integrity.v0.3"
    assert block["diff_stat"]["files_changed"] == 3
    assert any("test_demo.py" in p for p in block["test_files_changed"])
    assert any("pyproject.toml" in p for p in block["protected_path_touches"])
    assert any("test_demo.py" in p for p in block["protected_path_touches"])
    assert "pytest" in block["test_command"]
    assert block["test_exit_code"] == 0


def test_build_diff_test_integrity_does_not_fake_precision() -> None:
    block = build_diff_test_integrity({"paths_touched": ["src/x.py"], "commands_run": ["pytest"], "quality": {"passed": False}})
    # Fields that need real diff parsing stay null -- never invented.
    assert block["assertion_delta"]["assertions_added"] is None
    assert block["assertion_delta"]["assertions_removed"] is None
    assert block["mock_skip_signals"]["mocks_added"] is None
    assert block["mock_skip_signals"]["skips_added"] is None
    # v0.2: one touched path with no op-type source -> counted as unknown, not guessed.
    assert block["file_op_types"] == {"created": 0, "modified": 0, "deleted": 0, "renamed": 0, "unknown": 1}
    assert block["test_exit_code"] == 1  # failed quality -> non-zero


def test_build_diff_test_integrity_v02_rollups_are_honest() -> None:
    block = build_diff_test_integrity({
        "paths_touched": ["src/a.py", "tests/test_a.py", "tests/test_b.py", "pyproject.toml"],
        "commands_run": ["ruff check src", "pytest -q", "tox -e py"],
        "quality": {"passed": True},
    })
    # file_op_types: 4 paths, no op discrimination available -> all unknown.
    assert block["file_op_types"]["unknown"] == 4
    assert block["file_op_types"]["created"] == 0
    # test_signal rollups reflect the touched test files and the test commands.
    assert block["test_signal"]["test_files_touched_count"] == 2
    assert block["test_signal"]["test_command_present"] is True
    assert block["test_signal"]["test_command_count"] == 2  # pytest + tox, not ruff
    # protected_signal counts protected touches (tests + pyproject).
    assert block["protected_signal"]["protected_path_touch_count"] >= 3


def test_build_diff_test_integrity_v02_empty_rollups() -> None:
    block = build_diff_test_integrity({"incident_type": "SUPPORTED_CLAIM"})
    assert block["file_op_types"] == {"created": 0, "modified": 0, "deleted": 0, "renamed": 0, "unknown": 0}
    assert block["test_signal"]["test_files_touched_count"] == 0
    assert block["test_signal"]["test_command_present"] is False
    assert block["test_signal"]["test_command_count"] == 0
    assert block["protected_signal"]["protected_path_touch_count"] == 0


def test_all_unknown_file_op_types_does_not_inflate_coverage() -> None:
    record = {
        "incident_type": "CLAIM_WITHOUT_EVIDENCE",
        "paths_touched": ["src/a.py", "tests/test_a.py"],
        "commands_run": ["pytest -q"],
        "quality": {"passed": True},
    }
    record["diff_test_integrity"] = build_diff_test_integrity(record)
    fam = build_signal_coverage(record)["families"]["diff_test_integrity"]
    # diff_stat / test_exit_code are real captured signal; file_op_types is all
    # unknown -> it must NOT count as a captured future field.
    assert "diff_stat" in fam["fields_present"]
    assert "test_exit_code" in fam["fields_present"]
    assert "file_op_types" not in fam["fields_present"]
    # A real op type recorded later DOES lift file_op_types into coverage.
    record["diff_test_integrity"]["file_op_types"]["modified"] = 1
    fam2 = build_signal_coverage(record)["families"]["diff_test_integrity"]
    assert "file_op_types" in fam2["fields_present"]


def test_build_diff_test_integrity_empty_when_no_signal() -> None:
    block = build_diff_test_integrity({"incident_type": "SUPPORTED_CLAIM"})
    assert block["diff_stat"] == {}
    assert block["test_files_changed"] == []
    assert block["protected_path_touches"] == []
    assert block["test_command"] is None
    assert block["test_exit_code"] is None


def test_diff_test_capture_lifts_signal_coverage_to_partial() -> None:
    record = {
        "incident_type": "CLAIM_WITHOUT_EVIDENCE",
        "paths_touched": [r"D:\Repo\tests\test_demo.py"],
        "commands_run": ["pytest tests/test_demo.py"],
        "quality": {"passed": True},
    }
    before = build_signal_coverage(record)
    assert before["families"]["diff_test_integrity"]["status"] == "partial"  # paths_touched is current evidence
    record["diff_test_integrity"] = build_diff_test_integrity(record)
    after = build_signal_coverage(record)
    fam = after["families"]["diff_test_integrity"]
    # Captured future fields (diff_stat, test_exit_code) now count as present.
    assert "diff_stat" in fam["fields_present"]
    assert "test_exit_code" in fam["fields_present"]


def test_scan_source_signals_passes_benign() -> None:
    safe, safety = scan_source_signals(_signals(paths_touched=["src/a.py"], commands_run=["pytest -q"]))
    assert safety["scan_status"] == "PASS"
    assert safety["findings"] == []
    assert safety["redacted_fields"] == []
    assert safe["paths_touched"] == ["src/a.py"]


def test_scan_source_signals_noop_on_missing() -> None:
    safe, safety = scan_source_signals(None)
    assert safe is None
    assert safety["scan_status"] == "PASS"


def test_scan_source_signals_redacts_user_path_and_email() -> None:
    safe, safety = scan_source_signals(_signals(
        paths_touched=[r"C:/Users/sample-user/notes.py"],
        commands_run=["echo contact sagitariusart3d@gmail.com"],
    ))
    assert safety["scan_status"] == "REDACTED"
    # Username and email are scrubbed in place; nothing leaks into the safe copy.
    assert "sample-user" not in json.dumps(safe)
    assert "sagitariusart3d@gmail.com" not in json.dumps(safe)
    assert "<REDACTED_USER>" in safe["paths_touched"][0]
    assert "<REDACTED:EMAIL>" in safe["commands_run"][0]
    assert set(safety["redacted_fields"]) == {"paths_touched", "commands_run"}
    # Findings record detector + severity but never the raw secret.
    assert all("severity" in f and "detector" in f for f in safety["findings"])


def test_scan_source_signals_quarantines_secret() -> None:
    safe, safety = scan_source_signals(_signals(
        commands_run=[f"deploy --token={_REALISH_GH_TOKEN}"],
    ))
    assert safety["scan_status"] == "QUARANTINE"
    assert safety["quarantine_reason"] and "sensitive_source_signal_content" in safety["quarantine_reason"]
    # The secret is masked even in the safe copy, and never appears in findings.
    assert _REALISH_GH_TOKEN not in json.dumps(safe)
    assert _REALISH_GH_TOKEN not in json.dumps(safety["findings"])


def test_scan_source_signals_flags_dotenv_reference() -> None:
    _safe, safety = scan_source_signals(_signals(paths_touched=["config/.env"]))
    detectors = {f["detector"] for f in safety["findings"]}
    assert "dotenv_reference" in detectors
    assert safety["scan_status"] == "REDACTED"  # flagged for review, not quarantined
    # .env.example is a template, not a secret pointer -> no flag.
    _s2, safety2 = scan_source_signals(_signals(paths_touched=["config/.env.example"]))
    assert safety2["scan_status"] == "PASS"


def test_harvest_source_signals_captures_bones_from_receipt() -> None:
    receipt = {
        "repo": r"C:\Factory",
        "paths_touched": ["src/demo.py", "tests/test_demo.py", "pyproject.toml"],
        "commands_run": ["ruff check src", "pytest tests/test_demo.py -q"],
        "evidence": [{"path": r"C:\Factory\reports\x\latest.md", "status": "pass"}],
        "quality": {"passed": True},
    }
    sig = harvest_source_signals(receipt)
    assert sig["schema_version"] == "sf.source_signals.v0.4"
    assert sig["file_status"] == []  # no git status in this receipt -> empty
    assert sig["selected_tools"] == [] and sig["available_tools"] == []  # none in this receipt
    assert sig["diff_patch"] is None  # no diff text in this receipt -> null
    assert "src/demo.py" in sig["paths_touched"]
    # absolute path under the record's own repo is normalized to repo-relative.
    assert "reports/x/latest.md" in sig["paths_touched"]
    assert not any(":" in p for p in sig["paths_touched"])  # no drive-letter internal paths
    assert sig["changed_file_count"] == len(sig["paths_touched"])
    assert any("test_demo.py" in p for p in sig["test_files_touched"])
    assert any("pyproject.toml" in p for p in sig["protected_path_touches"])
    assert sig["test_command_present"] is True
    assert any("pytest" in c for c in sig["test_commands"])
    assert sig["command_surfaces"] == ["pytest", "ruff"]
    # raw per-command exit codes are not present in receipts -> never fabricated.
    assert sig["command_exit_codes"] == []


def test_harvest_source_signals_from_task_has_no_command_signal() -> None:
    task = {
        "repo_root": r"C:\Factory",
        "paths": ["src/y.py"],
        "evidence": [r"C:\Factory\reports\a\latest.md"],
    }
    sig = harvest_source_signals(task)
    assert "src/y.py" in sig["paths_touched"]
    assert "reports/a/latest.md" in sig["paths_touched"]  # repo_root used for normalization
    assert sig["commands_run"] == []
    assert sig["command_surfaces"] == []
    assert sig["test_commands"] == []
    assert sig["test_command_present"] is False


def test_harvest_source_signals_empty_is_honest() -> None:
    sig = harvest_source_signals({"incident_type": "SUPPORTED_CLAIM"})
    assert sig["paths_touched"] == []
    assert sig["changed_file_count"] == 0
    assert sig["commands_run"] == []
    assert sig["command_exit_codes"] == []
    assert sig["test_command_present"] is False
    assert sig["test_files_touched"] == []
    assert sig["protected_path_touches"] == []


def test_gold_builders_embed_source_signals() -> None:
    receipt = {
        "receipt_id": "r1", "repo": r"C:\Factory",
        "paths_touched": ["src/x.py", "tests/test_x.py"],
        "commands_run": ["pytest tests/test_x.py"],
        "evidence": [{"path": "src/x.py", "status": "pass"}],
        "quality": {"passed": True}, "outcome": "done",
    }
    row = receipt_gold_row(receipt, "SUPPORTED_CLAIM", "SAFE", "ok")
    assert row["source_signals"]["test_command_present"] is True
    assert row["source_signals"]["changed_file_count"] == 2

    task = {
        "id": "t1", "repo_root": r"C:\Factory", "status": "completed", "title": "t",
        "paths": ["src/yy.py"], "evidence": [{"path": "src/yy.py", "status": "pass"}],
    }
    grow = gold_coordination_row("sid", "fp", task)
    assert grow["source_signals"]["paths_touched"]  # lane/evidence paths preserved
    assert grow["source_signals"]["commands_run"] == []  # tasks carry no commands


def test_normalize_git_file_status_porcelain() -> None:
    blob = "A  src/new.py\n M src/mod.py\nD  src/gone.py\nR  src/old.py -> src/renamed.py\n?? src/untracked.py"
    entries = normalize_git_file_status(blob)
    by_path = {e["path"]: e["op"] for e in entries}
    assert by_path["src/new.py"] == "created"
    assert by_path["src/mod.py"] == "modified"
    assert by_path["src/gone.py"] == "deleted"
    assert by_path["src/renamed.py"] == "renamed"  # destination path wins
    assert by_path["src/untracked.py"] == "created"


def test_normalize_git_file_status_name_status() -> None:
    blob = "A\tsrc/new.py\nM\tsrc/mod.py\nD\tsrc/gone.py\nR100\tsrc/old.py\tsrc/renamed.py"
    entries = normalize_git_file_status(blob)
    by_path = {e["path"]: e["op"] for e in entries}
    assert by_path["src/new.py"] == "created"
    assert by_path["src/mod.py"] == "modified"
    assert by_path["src/gone.py"] == "deleted"
    assert by_path["src/renamed.py"] == "renamed"


def test_normalize_git_file_status_structured_and_unknown() -> None:
    entries = normalize_git_file_status([
        {"status": "A", "path": "a.py"},
        {"op": "deleted", "path": "b.py"},
        {"status": "X", "path": "weird.py"},  # unrecognized -> unknown
    ])
    by_path = {e["path"]: e["op"] for e in entries}
    assert by_path == {"a.py": "created", "b.py": "deleted", "weird.py": "unknown"}


def test_derive_file_op_types_counts_real_ops() -> None:
    counts = derive_file_op_types("A\tx.py\nM\ty.py\nM\tz.py\nD\tg.py\nR100\to.py\tn.py")
    assert counts == {"created": 1, "modified": 2, "deleted": 1, "renamed": 1, "unknown": 0}


def test_derive_file_op_types_none_without_status() -> None:
    assert derive_file_op_types(None) is None
    assert derive_file_op_types("") is None
    assert derive_file_op_types([]) is None


def test_build_diff_test_integrity_uses_real_file_status() -> None:
    record = {
        "incident_type": "CLAIM_WITHOUT_EVIDENCE",
        "source_signals": {
            "schema_version": "sf.source_signals.v0.2",
            "paths_touched": ["src/a.py", "src/b.py", "tests/test_a.py"],
            "commands_run": ["pytest -q"],
            "file_status": [
                {"op": "created", "path": "src/a.py"},
                {"op": "modified", "path": "src/b.py"},
                {"op": "modified", "path": "tests/test_a.py"},
            ],
        },
        "quality": {"passed": True},
    }
    block = build_diff_test_integrity(record)
    # Real op types replace all-unknown.
    assert block["file_op_types"] == {"created": 1, "modified": 2, "deleted": 0, "renamed": 0, "unknown": 0}
    record["diff_test_integrity"] = block
    fam = build_signal_coverage(record)["families"]["diff_test_integrity"]
    # Real ops mean file_op_types now counts as a captured coverage field.
    assert "file_op_types" in fam["fields_present"]


def test_build_diff_test_integrity_path_only_stays_unknown() -> None:
    record = {
        "incident_type": "CLAIM_WITHOUT_EVIDENCE",
        "source_signals": {
            "schema_version": "sf.source_signals.v0.2",
            "paths_touched": ["src/a.py", "src/b.py"],
            "commands_run": [],
            "file_status": [],  # no status -> no inference from paths
        },
    }
    block = build_diff_test_integrity(record)
    assert block["file_op_types"] == {"created": 0, "modified": 0, "deleted": 0, "renamed": 0, "unknown": 2}
    record["diff_test_integrity"] = block
    fam = build_signal_coverage(record)["families"]["diff_test_integrity"]
    assert "file_op_types" not in fam["fields_present"]  # all-unknown does not inflate


def test_harvest_captures_git_status_into_file_status() -> None:
    receipt = {
        "repo": r"C:\Factory",
        "paths_touched": ["src/a.py"],
        "git_status": "A  src/a.py\n M src/b.py",
    }
    sig = harvest_source_signals(receipt)
    by_path = {e["path"]: e["op"] for e in sig["file_status"]}
    assert by_path == {"src/a.py": "created", "src/b.py": "modified"}


def test_scan_redacts_secret_inside_file_status_path() -> None:
    _safe, safety = scan_source_signals({
        "schema_version": "sf.source_signals.v0.2",
        "paths_touched": [],
        "file_status": [{"op": "modified", "path": f"deploy --token={_REALISH_GH_TOKEN}"}],
    })
    # A secret hiding in git-status data is caught too -> quarantine.
    assert safety["scan_status"] == "QUARANTINE"
    assert any(f["field"] == "file_status" for f in safety["findings"])


def test_derive_assertion_delta_counts_added_and_removed() -> None:
    delta = derive_assertion_delta(_SAMPLE_DIFF)
    assert delta["assertions_added"] == 2  # two added assert lines
    assert delta["assertions_removed"] == 1  # one removed assert line


def test_derive_assertion_delta_null_without_diff() -> None:
    delta = derive_assertion_delta(None)
    assert delta == {"assertions_added": None, "assertions_removed": None}


def test_derive_mock_skip_signals_counts() -> None:
    signals = derive_mock_skip_signals(_SAMPLE_DIFF)
    assert signals["mocks_added"] == 1  # mocker.patch
    assert signals["xfail_added"] == 1  # one xfail line
    assert signals["skips_added"] == 2  # skipif + xfail (skip-or-xfail family)


def test_derive_mock_skip_signals_null_without_diff() -> None:
    assert derive_mock_skip_signals("") == {"mocks_added": None, "skips_added": None, "xfail_added": None}


def test_diff_parsers_ignore_metadata_lines() -> None:
    # +++ / --- / @@ headers contain words but must never count as changes.
    meta_only = "--- a/assert_helpers.py\n+++ b/assert_helpers.py\n@@ -1 +1 @@ assert mock skip\n context line\n"
    assert derive_assertion_delta(meta_only) == {"assertions_added": 0, "assertions_removed": 0}
    assert derive_mock_skip_signals(meta_only) == {"mocks_added": 0, "skips_added": 0, "xfail_added": 0}


def test_extract_diff_text_from_signals_and_record() -> None:
    assert extract_diff_text({"source_signals": {"diff_patch": "+ assert x"}}) == "+ assert x"
    assert extract_diff_text({"git_diff": ["+ assert x", "- assert y"]}) == "+ assert x\n- assert y"
    assert extract_diff_text({"incident_type": "X"}) is None


def test_build_diff_test_integrity_parses_diff_when_present() -> None:
    record = {
        "incident_type": "CLAIM_WITHOUT_EVIDENCE",
        "source_signals": {"schema_version": "sf.source_signals.v0.2", "paths_touched": ["tests/test_x.py"], "diff_patch": _SAMPLE_DIFF},
    }
    block = build_diff_test_integrity(record)
    assert block["schema_version"] == "sf.diff_test_integrity.v0.3"
    assert block["assertion_delta"]["assertions_added"] == 2
    assert block["assertion_delta"]["assertions_removed"] == 1
    assert block["mock_skip_signals"]["mocks_added"] == 1


def test_build_diff_test_integrity_nulls_without_diff() -> None:
    block = build_diff_test_integrity({"paths_touched": ["src/a.py"]})
    assert block["assertion_delta"] == {"assertions_added": None, "assertions_removed": None}
    assert block["mock_skip_signals"] == {"mocks_added": None, "skips_added": None, "xfail_added": None}


def test_harvest_captures_diff_patch() -> None:
    receipt = {"repo": r"C:\Factory", "paths_touched": ["src/a.py"], "git_diff": _SAMPLE_DIFF}
    sig = harvest_source_signals(receipt)
    assert sig["schema_version"] == "sf.source_signals.v0.4"
    assert sig["diff_patch"] == _SAMPLE_DIFF
    # No diff text -> null, never fabricated.
    assert harvest_source_signals({"paths_touched": ["src/a.py"]})["diff_patch"] is None


def test_scan_quarantines_secret_in_diff_patch() -> None:
    _safe, safety = scan_source_signals({
        "schema_version": "sf.source_signals.v0.3",
        "paths_touched": [],
        "diff_patch": f'+    API_KEY = "{_REALISH_GH_TOKEN}"\n',
    })
    assert safety["scan_status"] == "QUARANTINE"
    assert any(f["field"] == "diff_patch" for f in safety["findings"])


def test_scan_does_not_quarantine_legit_auth_code_in_diff() -> None:
    # Real code that mentions token/secret variables must NOT be quarantined --
    # only literal secrets are severe in diff text.
    _safe, safety = scan_source_signals({
        "schema_version": "sf.source_signals.v0.3",
        "paths_touched": [],
        "diff_patch": "+    token = request.headers.get('Authorization')\n+    assert secret == expected_secret\n",
    })
    assert safety["scan_status"] == "PASS"


def test_fixture_token_in_test_file_is_redacted_not_quarantined() -> None:
    safe, safety = scan_source_signals({"schema_version": "sf.source_signals.v0.3", "paths_touched": [], "diff_patch": _FIXTURE_DIFF})
    # Clearly-fake token + test-file context -> REDACTED, not quarantined.
    assert safety["scan_status"] == "REDACTED"
    assert any(f["severity"] == "fixture" and f.get("action") == "redacted_not_quarantined" for f in safety["findings"])
    assert all(f["severity"] != "severe" for f in safety["findings"])
    # The token is still scrubbed, but the assertion line survives for the parser.
    assert "ghp_FAKEexampletoken000000000000" not in safe["diff_patch"]
    assert "assert client.authed is True" in safe["diff_patch"]


def test_real_looking_token_in_test_file_still_quarantines() -> None:
    # Strict: a real-looking token in a test file still quarantines -- humans do
    # leak real secrets into tests.
    diff = f'+++ b/tests/test_auth.py\n+    TOKEN = "{_REALISH_GH_TOKEN}"\n'
    _safe, safety = scan_source_signals({"schema_version": "sf.source_signals.v0.3", "paths_touched": [], "diff_patch": diff})
    assert safety["scan_status"] == "QUARANTINE"


def test_fixture_token_outside_test_context_still_quarantines() -> None:
    # Fakeness alone is not enough: a fake token in non-test code quarantines.
    diff = '+++ b/src/auth.py\n+    TOKEN = "ghp_FAKEexampletoken000000000000"\n'
    _safe, safety = scan_source_signals({"schema_version": "sf.source_signals.v0.3", "paths_touched": [], "diff_patch": diff})
    assert safety["scan_status"] == "QUARANTINE"


def test_strip_diff_text_from_row_keeps_counts_drops_patch() -> None:
    row = {
        "fingerprint": "fp", "diff_patch": "raw top-level",
        "source_signals": {"paths_touched": ["a.py"], "diff_patch": "raw patch text"},
        "diff_test_integrity": {"assertion_delta": {"assertions_added": 2}},
    }
    out = strip_diff_text_from_row(row)
    assert "diff_patch" not in out
    assert "diff_patch" not in out["source_signals"]
    assert out["source_signals"]["paths_touched"] == ["a.py"]
    assert out["diff_test_integrity"]["assertion_delta"]["assertions_added"] == 2
