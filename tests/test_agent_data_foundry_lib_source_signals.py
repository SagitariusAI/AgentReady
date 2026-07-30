from __future__ import annotations

from agent_data_foundry_lib.source_signals import (
    _is_protected_path,
    _is_test_path,
    build_diff_test_integrity,
    build_file_op_types,
    build_tool_call_trajectory,
    derive_assertion_delta,
    derive_file_op_types,
    derive_mock_skip_signals,
    extract_diff_text,
    harvest_source_signals,
    normalize_git_file_status,
    strip_diff_text_from_row,
)

_REAL_DIFF = (
    "diff --git a/src/x.py b/src/x.py\n"
    "--- a/src/x.py\n"
    "+++ b/src/x.py\n"
    "@@ -1,2 +1,4 @@\n"
    "+    assert x == 1\n"
    "+    mocker.patch('m')\n"
    "-    assert old\n"
    "+    @pytest.mark.skip\n"
)


def test_harvest_schema_and_honest_emptiness() -> None:
    sig = harvest_source_signals({"incident_type": "SUPPORTED_CLAIM"})
    assert sig["schema_version"] == "sf.source_signals.v0.4"
    # nothing fabricated when the record carries nothing
    assert sig["paths_touched"] == [] and sig["changed_file_count"] == 0
    assert sig["diff_patch"] is None and sig["command_exit_codes"] == []
    assert sig["test_command_present"] is False


def test_harvest_repo_relative_paths_and_test_detection() -> None:
    sig = harvest_source_signals({
        "repo": r"C:\Factory",
        "paths_touched": [r"C:\Factory\src\x.py", r"C:\Factory\tests\test_x.py"],
        "commands_run": ["pytest tests/test_x.py", "ruff check"],
    })
    assert sig["paths_touched"] == ["src/x.py", "tests/test_x.py"]  # repo prefix stripped, POSIX
    assert sig["test_files_touched"] == ["tests/test_x.py"]
    assert sig["test_command_present"] is True
    assert "pytest" in sig["command_surfaces"] and "ruff" in sig["command_surfaces"]


def test_path_only_file_ops_stay_unknown() -> None:
    # A bare path list carries no op-type, so every touched path is `unknown`.
    assert build_file_op_types(["a.py", "b.py"]) == {"created": 0, "modified": 0, "deleted": 0, "renamed": 0, "unknown": 2}
    block = build_diff_test_integrity({"paths_touched": ["src/a.py", "src/b.py"]})
    assert block["file_op_types"]["unknown"] == 2 and block["file_op_types"]["modified"] == 0


def test_real_git_status_counts_each_op() -> None:
    counts = derive_file_op_types("A\tnew.py\nM\tmod.py\nM\tmod2.py\nD\tgone.py\nR100\told.py\tnew2.py")
    assert counts == {"created": 1, "modified": 2, "deleted": 1, "renamed": 1, "unknown": 0}
    # no status data -> None so the caller falls back to all-unknown (never guessed)
    assert derive_file_op_types(None) is None
    assert derive_file_op_types("") is None
    assert derive_file_op_types([]) is None


def test_normalize_git_status_porcelain_and_structured() -> None:
    porcelain = normalize_git_file_status(" M src/x.py\n?? new.py\nR  old.py -> new.py")
    assert {"op": "modified", "path": "src/x.py"} in porcelain
    assert {"op": "created", "path": "new.py"} in porcelain
    assert {"op": "renamed", "path": "new.py"} in porcelain
    structured = normalize_git_file_status([{"status": "A", "path": "a.py"}, {"op": "deleted", "path": "b.py"}])
    assert structured == [{"op": "created", "path": "a.py"}, {"op": "deleted", "path": "b.py"}]


def test_diff_test_integrity_schema_and_deltas() -> None:
    block = build_diff_test_integrity({"source_signals": {"diff_patch": _REAL_DIFF, "paths_touched": ["src/x.py"]}})
    assert block["schema_version"] == "sf.diff_test_integrity.v0.3"
    assert block["assertion_delta"] == {"assertions_added": 1, "assertions_removed": 1}
    assert block["mock_skip_signals"] == {"mocks_added": 1, "skips_added": 1, "xfail_added": 0}


def test_assertion_and_mock_deltas_are_null_without_diff() -> None:
    assert derive_assertion_delta(None) == {"assertions_added": None, "assertions_removed": None}
    assert derive_mock_skip_signals(None) == {"mocks_added": None, "skips_added": None, "xfail_added": None}
    # meta-only diff lines (+++/---/@@) must not count as code changes
    meta = "+++ b/x.py\n--- a/x.py\n@@ -1 +1 @@\n"
    assert derive_assertion_delta(meta) == {"assertions_added": 0, "assertions_removed": 0}


def test_extract_diff_text_prefers_source_signals() -> None:
    assert extract_diff_text({"source_signals": {"diff_patch": "+ assert x"}}) == "+ assert x"
    assert extract_diff_text({"git_diff": ["+ a", "- b"]}) == "+ a\n- b"
    assert extract_diff_text({"incident_type": "X"}) is None


def test_strip_diff_text_keeps_counts_drops_patch() -> None:
    row = {"fingerprint": "fp", "diff_patch": "secret diff", "source_signals": {"diff_patch": "secret", "paths_touched": ["a.py"]}}
    cleaned = strip_diff_text_from_row(row)
    assert "diff_patch" not in cleaned
    assert "diff_patch" not in cleaned["source_signals"]
    assert cleaned["source_signals"]["paths_touched"] == ["a.py"]  # non-diff fields preserved


def test_tool_call_trajectory_source_labelling() -> None:
    # explicit tool record -> tool_record
    rec = build_tool_call_trajectory({"selected_tools": ["ruff", "pytest"], "available_tools": ["ruff", "pytest", "mypy"]})
    assert rec["schema_version"] == "sf.tool_call_trajectory.v0.1"
    assert rec["trajectory_source"] == "tool_record" and rec["tool_sequence"] == ["ruff", "pytest"]
    # only commands -> command_receipt (a command sequence is NOT model tool-call reasoning)
    cmd = build_tool_call_trajectory({"commands_run": ["pytest -q", "ruff check"]})
    assert cmd["trajectory_source"] == "command_receipt" and cmd["tool_sequence"] == ["pytest", "ruff"]
    # nothing -> missing
    assert build_tool_call_trajectory({"incident_type": "X"})["trajectory_source"] == "missing"


def test_protected_and_test_path_classifiers() -> None:
    assert _is_test_path("tests/test_x.py") is True
    assert _is_protected_path("docs/AGENT_CONSTITUTION.md") is True
    assert _is_protected_path("pyproject.toml") is True
    assert _is_test_path("src/app.py") is False


def test_reexported_identity_from_agent_data_foundry() -> None:
    import agent_data_foundry as adf

    for name in (
        "harvest_source_signals", "build_diff_test_integrity", "build_tool_call_trajectory",
        "strip_diff_text_from_row", "normalize_git_file_status", "derive_file_op_types",
        "extract_diff_text", "derive_assertion_delta", "derive_mock_skip_signals",
    ):
        assert getattr(adf, name) is globals()[name] or getattr(adf, name).__name__ == name
    assert adf.harvest_source_signals is harvest_source_signals
    assert adf.normalize_git_file_status is normalize_git_file_status
