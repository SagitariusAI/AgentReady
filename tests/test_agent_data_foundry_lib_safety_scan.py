# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json

from agent_data_foundry_lib.safety_scan import (
    SOURCE_SIGNAL_SCAN_FIELDS,
    _is_test_or_fixture_path,
    _looks_like_fake_secret,
    _scan_source_signal_value,
    scan_source_signals,
)

# A token that matches the github_token severe detector but carries NO fake marker,
# so it is treated as a real leak everywhere (commands, file_status, src diffs) and
# only the diff-in-test-path + fake-marker path can downgrade it.
_REALISH_GH_TOKEN = "ghp_" + "ab" * 18


def _signals(**over):
    base = {"schema_version": "sf.source_signals.v0.1", "paths_touched": [], "commands_run": []}
    base.update(over)
    return base


def test_benign_signals_pass() -> None:
    safe, safety = scan_source_signals(_signals(paths_touched=["src/a.py"], commands_run=["pytest -q"]))
    assert safety["scan_status"] == "PASS"
    assert safety["findings"] == [] and safety["redacted_fields"] == []
    assert safe["paths_touched"] == ["src/a.py"]


def test_non_dict_is_noop_pass() -> None:
    safe, safety = scan_source_signals(None)
    assert safe is None and safety["scan_status"] == "PASS"
    assert safety["schema_version"] == "sf.source_signal_safety.v0.1"


def test_user_path_and_email_redacted_in_place_no_leak() -> None:
    safe, safety = scan_source_signals(_signals(
        paths_touched=[r"C:/Users/sample-user/notes.py"],
        commands_run=["echo contact dev@example.org"],
    ))
    assert safety["scan_status"] == "REDACTED"
    blob = json.dumps(safe)
    assert "sample-user" not in blob and "dev@example.org" not in blob  # raw values = 0 in stored copy
    assert "<REDACTED_USER>" in safe["paths_touched"][0]
    assert "<REDACTED:EMAIL>" in safe["commands_run"][0]
    assert set(safety["redacted_fields"]) == {"paths_touched", "commands_run"}


def test_realish_secret_quarantines_and_never_leaks() -> None:
    safe, safety = scan_source_signals(_signals(commands_run=[f"deploy --token={_REALISH_GH_TOKEN}"]))
    assert safety["scan_status"] == "QUARANTINE"
    assert "sensitive_source_signal_content" in (safety["quarantine_reason"] or "")
    # Raw token = 0 in both the safe copy and the findings (findings carry detector only).
    assert _REALISH_GH_TOKEN not in json.dumps(safe)
    assert _REALISH_GH_TOKEN not in json.dumps(safety["findings"])
    assert all("severity" in f and "detector" in f for f in safety["findings"])


def test_secret_in_file_status_path_quarantines() -> None:
    _safe, safety = scan_source_signals({
        "schema_version": "sf.source_signals.v0.3",
        "file_status": [{"op": "modified", "path": f"deploy --token={_REALISH_GH_TOKEN}"}],
    })
    assert safety["scan_status"] == "QUARANTINE"
    assert any(f["field"] == "file_status" for f in safety["findings"])


def test_dotenv_path_flagged_but_example_passes() -> None:
    _safe, safety = scan_source_signals(_signals(paths_touched=["config/.env"]))
    assert safety["scan_status"] == "REDACTED"
    assert "dotenv_reference" in {f["detector"] for f in safety["findings"]}
    _s2, safety2 = scan_source_signals(_signals(paths_touched=["config/.env.example"]))
    assert safety2["scan_status"] == "PASS"


def test_fake_fixture_token_in_test_diff_is_redacted_not_quarantined() -> None:
    # Clearly-fake token (has "FAKE"/"example") AND a test-file path -> REDACTED-kept,
    # so the Factory can still learn from its own security-test diffs. Raw token = 0.
    diff = (
        "diff --git a/tests/test_auth.py b/tests/test_auth.py\n"
        "+++ b/tests/test_auth.py\n"
        '+    TOKEN = "ghp_FAKEexampletoken000000000000"\n'
    )
    safe, safety = scan_source_signals({"schema_version": "sf.source_signals.v0.3", "paths_touched": [], "diff_patch": diff})
    assert safety["scan_status"] == "REDACTED"
    assert any(f.get("action") == "redacted_not_quarantined" for f in safety["findings"])
    assert "ghp_FAKEexampletoken000000000000" not in json.dumps(safe)


def test_realish_token_in_test_diff_still_quarantines() -> None:
    # Fakeness is REQUIRED for the carveout: a real-looking token in a test file
    # still quarantines (humans do leak real secrets into tests).
    diff = f'+++ b/tests/test_auth.py\n+    TOKEN = "{_REALISH_GH_TOKEN}"\n'
    _safe, safety = scan_source_signals({"schema_version": "sf.source_signals.v0.3", "paths_touched": [], "diff_patch": diff})
    assert safety["scan_status"] == "QUARANTINE"


def test_fake_token_outside_test_context_quarantines() -> None:
    # Test-path context is also REQUIRED: a fake token in src code quarantines.
    diff = '+++ b/src/auth.py\n+    TOKEN = "ghp_FAKEexampletoken000000000000"\n'
    _safe, safety = scan_source_signals({"schema_version": "sf.source_signals.v0.3", "paths_touched": [], "diff_patch": diff})
    assert safety["scan_status"] == "QUARANTINE"


def test_legit_auth_variable_code_not_quarantined() -> None:
    # token = get_token() style code is not a literal secret -> not severe.
    _safe, safety = scan_source_signals({
        "schema_version": "sf.source_signals.v0.3",
        "paths_touched": [],
        "diff_patch": "+    token = request.headers.get('Authorization')\n+    assert secret == expected_secret\n",
    })
    assert safety["scan_status"] != "QUARANTINE"


def test_scan_value_helper_contract() -> None:
    out, findings, redacted, severe = _scan_source_signal_value(f"x {_REALISH_GH_TOKEN} y")
    assert severe is True and redacted is True
    assert _REALISH_GH_TOKEN not in out and "<REDACTED:GITHUB_TOKEN>" in out
    assert all("detector" in f and "severity" in f for f in findings)
    assert _REALISH_GH_TOKEN not in json.dumps(findings)


def test_fixture_and_path_classifiers() -> None:
    assert _looks_like_fake_secret("ghp_FAKEexample") is True
    assert _looks_like_fake_secret(_REALISH_GH_TOKEN) is False
    assert _is_test_or_fixture_path("tests/test_x.py") is True
    assert _is_test_or_fixture_path("src/app.py") is False
    assert _is_test_or_fixture_path("/dev/null") is False
    assert "diff_patch" not in SOURCE_SIGNAL_SCAN_FIELDS  # diff is scanned separately, not as a list field


def test_reexported_from_agent_data_foundry() -> None:
    import agent_data_foundry as adf

    assert adf.scan_source_signals is scan_source_signals
    assert adf._scan_source_signal_value is _scan_source_signal_value
