# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Hermetic unit tests for agent_deterministic_toolbox.

These tests monkeypatch the filesystem report root, the subprocess/shutil
boundaries, importlib spec lookup, and __import__ so that no test depends on
which deterministic tools happen to be installed on the host.
"""
from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import agent_deterministic_toolbox as mod  # noqa: E402

# ---------------------------------------------------------------------------
# ToolStatus dataclass
# ---------------------------------------------------------------------------


def test_toolstatus_is_dataclass_with_fields():
    status = mod.ToolStatus(
        name="numpy", kind="python", installed=True, version="1.2.3", purpose="arrays"
    )
    assert asdict(status) == {
        "name": "numpy",
        "kind": "python",
        "installed": True,
        "version": "1.2.3",
        "purpose": "arrays",
    }


# ---------------------------------------------------------------------------
# module_version
# ---------------------------------------------------------------------------


_SENTINEL_MODNAME = "agentready_fake_probe_module"


def _import_shim(intercept, replacement):
    """Build an __import__ replacement that intercepts one name only.

    Every other import is delegated to the real builtin so pytest's own
    machinery (warnings, plugins) keeps working while patched.
    """
    import builtins

    real = builtins.__import__

    def shim(name, *a, **k):
        if name == intercept:
            return replacement(name)
        return real(name, *a, **k)

    return shim


def test_module_version_reads_dunder_version(monkeypatch):
    class FakeMod:
        __version__ = "9.9.9"

    import builtins

    monkeypatch.setattr(
        builtins, "__import__", _import_shim(_SENTINEL_MODNAME, lambda n: FakeMod())
    )
    assert mod.module_version(_SENTINEL_MODNAME) == "9.9.9"


def test_module_version_defaults_to_installed_when_no_version(monkeypatch):
    class FakeMod:
        pass

    import builtins

    monkeypatch.setattr(
        builtins, "__import__", _import_shim(_SENTINEL_MODNAME, lambda n: FakeMod())
    )
    assert mod.module_version(_SENTINEL_MODNAME) == "installed"


def test_module_version_handles_import_error(monkeypatch):
    import builtins

    def raise_import(name):
        raise ImportError("no such module foo")

    monkeypatch.setattr(
        builtins, "__import__", _import_shim(_SENTINEL_MODNAME, raise_import)
    )
    out = mod.module_version(_SENTINEL_MODNAME)
    assert out.startswith("error:")
    assert "no such module foo" in out


# ---------------------------------------------------------------------------
# module_status
# ---------------------------------------------------------------------------


def test_module_status_installed(monkeypatch):
    monkeypatch.setattr(mod.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(mod, "module_version", lambda name: "5.0")
    status = mod.module_status("z3-solver", "boolean logic", import_name="z3")
    assert status.name == "z3-solver"
    assert status.kind == "python"
    assert status.installed is True
    assert status.version == "5.0"
    assert status.purpose == "boolean logic"


def test_module_status_not_installed_has_blank_version(monkeypatch):
    monkeypatch.setattr(mod.importlib.util, "find_spec", lambda name: None)
    called = {"n": 0}

    def fail(name):
        called["n"] += 1
        return "should-not-be-used"

    monkeypatch.setattr(mod, "module_version", fail)
    status = mod.module_status("ghostlib", "nothing")
    assert status.installed is False
    assert status.version == ""
    # version is not probed when not installed
    assert called["n"] == 0


def test_module_status_defaults_import_name_to_name(monkeypatch):
    seen = {}

    def fake_find_spec(name):
        seen["name"] = name
        return None

    monkeypatch.setattr(mod.importlib.util, "find_spec", fake_find_spec)
    mod.module_status("numpy", "arrays")
    assert seen["name"] == "numpy"


# ---------------------------------------------------------------------------
# command_status
# ---------------------------------------------------------------------------


def test_command_status_not_on_path(monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: None)
    status = mod.command_status("nope", "missing tool")
    assert status.installed is False
    assert status.version == ""
    assert status.kind == "command"
    assert status.purpose == "missing tool"


def test_command_status_uses_stdout_first_line(monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/jq")

    class Probe:
        stdout = "jq-1.7.1\nignored second line"
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: Probe())
    status = mod.command_status("jq", "json")
    assert status.installed is True
    assert status.version == "jq-1.7.1"


def test_command_status_falls_back_to_stderr(monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/node")

    class Probe:
        stdout = ""
        stderr = "v20.0.0\nrest"

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: Probe())
    status = mod.command_status("node", "js")
    assert status.version == "v20.0.0"


def test_command_status_empty_output_uses_path(monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/bin/python")

    class Probe:
        stdout = ""
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: Probe())
    status = mod.command_status("python", "baseline")
    assert status.version == "/bin/python"


def test_command_status_truncates_long_version(monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/bin/rg")
    long_line = "x" * 500

    class Probe:
        stdout = long_line
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: Probe())
    status = mod.command_status("rg", "search")
    assert len(status.version) == 160
    assert status.version == "x" * 160


def test_command_status_subprocess_exception_falls_back_to_path(monkeypatch):
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/bin/octave")

    def boom(*a, **k):
        raise mod.subprocess.TimeoutExpired(cmd="octave", timeout=8)

    monkeypatch.setattr(mod.subprocess, "run", boom)
    status = mod.command_status("octave", "matlab-like")
    assert status.installed is True
    assert status.version == "/bin/octave"


# ---------------------------------------------------------------------------
# run_smokes
# ---------------------------------------------------------------------------


def test_run_smokes_returns_records_for_all_checks():
    results = mod.run_smokes()
    names = {r["name"] for r in results}
    assert names == {
        "sympy_quadratic",
        "z3_boolean_logic",
        "pandas_groupby",
        "duckdb_sql",
        "networkx_path",
    }
    for r in results:
        assert set(r.keys()) == {"name", "ok", "detail"}
        assert isinstance(r["ok"], bool)
        assert isinstance(r["detail"], str)


def test_run_smokes_records_failure_when_import_blocked(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def blocked(name, *a, **k):
        if name in {"sympy", "z3", "pandas", "duckdb", "networkx"}:
            raise ImportError(f"blocked {name}")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", blocked)
    results = mod.run_smokes()
    assert len(results) == 5
    assert all(r["ok"] is False for r in results)
    # detail should carry the blocked import message for at least one
    assert any("blocked" in r["detail"] for r in results)


# ---------------------------------------------------------------------------
# build_payload
# ---------------------------------------------------------------------------


def _patch_tool_probes(monkeypatch, installed=True):
    """Make module/command probes deterministic regardless of host."""
    monkeypatch.setattr(
        mod.importlib.util, "find_spec", lambda name: object() if installed else None
    )
    monkeypatch.setattr(mod, "module_version", lambda name: "1.0")
    monkeypatch.setattr(
        mod.shutil, "which", lambda name: "/bin/" + name if installed else None
    )

    class Probe:
        stdout = "ver 1.0"
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: Probe())


def test_build_payload_with_smokes(monkeypatch):
    _patch_tool_probes(monkeypatch, installed=True)
    monkeypatch.setattr(
        mod,
        "run_smokes",
        lambda: [
            {"name": "a", "ok": True, "detail": "d1"},
            {"name": "b", "ok": True, "detail": "d2"},
        ],
    )
    payload = mod.build_payload(run_smoke=True)
    assert payload["tool_count"] == 19  # 10 python + 9 command
    assert payload["installed_count"] == 19
    # Tool Inventory Scope contract: the count is never naked -- it carries its scope + sources.
    assert payload["inventory_scope"] == "isolated_tool_venv_tools"
    assert payload["inventory_scope"] in mod.INVENTORY_SCOPES
    assert payload["topology_source"] and payload["visibility_source"]
    # source -> authority model: this scope sits in the scoped_visibility layer
    assert payload["capability_layer"] == "scoped_visibility"
    assert payload["capability_layer"] == mod.SCOPE_LAYER[payload["inventory_scope"]]
    # a scan is NOT the authoritative total; that lives in installed package metadata
    assert payload["authoritative_total_installed_count"] is None
    assert "package metadata" in payload["authoritative_total_installed_source"]
    assert "multi-scope" in payload["interpretation"]
    assert "install manifest" in payload["interpretation"]
    mod.require_inventory_scope(payload)  # must not raise
    assert payload["smoke_ok"] is True
    assert len(payload["smoke_tests"]) == 2
    assert payload["python"] == sys.executable
    assert isinstance(payload["generated_at"], str)
    assert "Local models must cite" in payload["local_model_rule"]
    # tools are serialized dicts, not dataclasses
    assert all(isinstance(t, dict) for t in payload["tools"])
    assert payload["tools"][0]["name"] == "numpy"


def test_build_payload_smoke_ok_false_when_a_check_fails(monkeypatch):
    _patch_tool_probes(monkeypatch, installed=True)
    monkeypatch.setattr(
        mod,
        "run_smokes",
        lambda: [
            {"name": "a", "ok": True, "detail": "d1"},
            {"name": "b", "ok": False, "detail": "boom"},
        ],
    )
    payload = mod.build_payload(run_smoke=True)
    assert payload["smoke_ok"] is False


def test_build_payload_no_smoke(monkeypatch):
    _patch_tool_probes(monkeypatch, installed=False)
    # run_smokes must not be invoked when run_smoke=False
    monkeypatch.setattr(
        mod, "run_smokes", lambda: (_ for _ in ()).throw(AssertionError("should not run"))
    )
    payload = mod.build_payload(run_smoke=False)
    assert payload["smoke_tests"] == []
    assert payload["smoke_ok"] is None
    assert payload["installed_count"] == 0
    assert payload["tool_count"] == 19


# ---------------------------------------------------------------------------
# write_report
# ---------------------------------------------------------------------------


def _sample_payload(with_smokes=True):
    payload = {
        "generated_at": "2026-06-14T00:00:00+00:00",
        "python": "/usr/bin/python",
        "inventory_scope": "isolated_tool_venv_tools",
        "capability_layer": "scoped_visibility",
        "tool_count": 2,
        "installed_count": 1,
        "topology_source": "src/agent_deterministic_toolbox.py:build_payload (curated deterministic-tool topology)",
        "visibility_source": "importlib.util.find_spec + shutil.which on /usr/bin/python / machine PATH",
        "authoritative_total_installed_count": None,
        "authoritative_total_installed_source": "install manifest (packaging/install record + SBOM)",
        "interpretation": "Software Factory tool inventory is multi-scope. Scoped visibility report.",
        "tools": [
            {
                "name": "numpy",
                "kind": "python",
                "installed": True,
                "version": "1.0",
                "purpose": "arrays | vectors",
            },
            {
                "name": "jq",
                "kind": "command",
                "installed": False,
                "version": "",
                "purpose": "json",
            },
        ],
        "smoke_tests": [],
        "smoke_ok": None,
        "local_model_rule": "Local models must cite deterministic tool output.",
    }
    if with_smokes:
        payload["smoke_tests"] = [
            {"name": "sympy_quadratic", "ok": True, "detail": "roots=[2, 3]"},
            {"name": "z3_boolean_logic", "ok": False, "detail": "a | b detail"},
        ]
        payload["smoke_ok"] = False
    return payload


def test_write_report_creates_files_and_latest(monkeypatch, tmp_path):
    report_root = tmp_path / "reports" / "deterministic-toolbox"
    monkeypatch.setattr(mod, "REPORT_ROOT", report_root)

    payload = _sample_payload(with_smokes=True)
    md_path = mod.write_report(payload)

    assert md_path.exists()
    assert md_path.parent == report_root
    assert md_path.suffix == ".md"

    # JSON sibling exists with same stem
    json_path = md_path.with_suffix(".json")
    assert json_path.exists()
    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded == payload

    # latest.* mirrors
    latest_json = report_root / "latest.json"
    latest_md = report_root / "latest.md"
    assert latest_json.exists()
    assert latest_md.exists()
    assert json.loads(latest_json.read_text(encoding="utf-8")) == payload
    assert latest_md.read_text(encoding="utf-8") == md_path.read_text(encoding="utf-8")


def test_write_report_markdown_content(monkeypatch, tmp_path):
    report_root = tmp_path / "reports" / "deterministic-toolbox"
    monkeypatch.setattr(mod, "REPORT_ROOT", report_root)

    payload = _sample_payload(with_smokes=True)
    md_path = mod.write_report(payload)
    text = md_path.read_text(encoding="utf-8")

    assert "# AgentReady Deterministic Toolbox" in text
    # scope-labeled count with its capability layer, never a naked total
    assert "- Inventory scope: `isolated_tool_venv_tools`" in text
    assert "capability layer: `scoped_visibility`" in text
    assert "- Installed in this scope: 1 / 2" in text
    assert "- Installed tools: 1 / 2" not in text  # the old naked-total line is gone
    assert "install manifest" in text  # authoritative total points at the manifest, not this scan
    assert "## Inventory Scope" in text
    assert "- Smoke OK: `False`" in text
    assert "## Tool Inventory" in text
    assert "| numpy | python | True |" in text
    # pipe chars inside fields are escaped to '/'
    assert "arrays / vectors" in text
    assert "|" not in "arrays / vectors"
    # smoke section is rendered because smoke_tests is non-empty
    assert "## Smoke Tests" in text
    assert "| sympy_quadratic | True | roots=[2, 3] |" in text
    # smoke detail pipe escaped
    assert "a / b detail" in text


def test_write_report_omits_smoke_section_when_empty(monkeypatch, tmp_path):
    report_root = tmp_path / "reports" / "deterministic-toolbox"
    monkeypatch.setattr(mod, "REPORT_ROOT", report_root)

    payload = _sample_payload(with_smokes=False)
    md_path = mod.write_report(payload)
    text = md_path.read_text(encoding="utf-8")

    assert "## Smoke Tests" not in text
    assert "- Smoke OK: `None`" in text


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------


def test_main_default_runs_smokes_and_returns_zero(monkeypatch, tmp_path, capsys):
    report_root = tmp_path / "reports" / "deterministic-toolbox"
    monkeypatch.setattr(mod, "REPORT_ROOT", report_root)
    monkeypatch.setattr(sys, "argv", ["prog"])

    captured = {}

    def fake_build(run_smoke):
        captured["run_smoke"] = run_smoke
        return _sample_payload(with_smokes=False)  # smoke_ok None -> rc 0

    monkeypatch.setattr(mod, "build_payload", fake_build)

    rc = mod.main()
    assert rc == 0
    assert captured["run_smoke"] is True
    out = capsys.readouterr().out
    assert "AgentReady deterministic toolbox:" in out
    # the printed path should point inside the patched report root
    assert str(report_root) in out


def test_main_no_smoke_flag(monkeypatch, tmp_path):
    report_root = tmp_path / "reports" / "deterministic-toolbox"
    monkeypatch.setattr(mod, "REPORT_ROOT", report_root)
    monkeypatch.setattr(sys, "argv", ["prog", "--no-smoke"])

    captured = {}

    def fake_build(run_smoke):
        captured["run_smoke"] = run_smoke
        return _sample_payload(with_smokes=False)

    monkeypatch.setattr(mod, "build_payload", fake_build)
    rc = mod.main()
    assert rc == 0
    assert captured["run_smoke"] is False


def test_main_returns_two_on_smoke_failure(monkeypatch, tmp_path):
    report_root = tmp_path / "reports" / "deterministic-toolbox"
    monkeypatch.setattr(mod, "REPORT_ROOT", report_root)
    monkeypatch.setattr(sys, "argv", ["prog"])

    monkeypatch.setattr(
        mod, "build_payload", lambda run_smoke: _sample_payload(with_smokes=True)
    )  # smoke_ok False -> rc 2
    rc = mod.main()
    assert rc == 2


def test_main_full_integration_writes_real_files(monkeypatch, tmp_path):
    """End-to-end through real build_payload + write_report with patched probes."""
    report_root = tmp_path / "reports" / "deterministic-toolbox"
    monkeypatch.setattr(mod, "REPORT_ROOT", report_root)
    monkeypatch.setattr(sys, "argv", ["prog", "--no-smoke"])
    _patch_tool_probes(monkeypatch, installed=True)

    rc = mod.main()
    assert rc == 0
    assert (report_root / "latest.json").exists()
    latest = json.loads((report_root / "latest.json").read_text(encoding="utf-8"))
    assert latest["tool_count"] == 19
    assert latest["installed_count"] == 19
    assert latest["smoke_ok"] is None
    # every persisted tool-count report carries its inventory scope
    assert latest["inventory_scope"] == "isolated_tool_venv_tools"


# ---------------------------------------------------------------------------
# Tool Inventory Scope contract (regression): no tool count without its scope
# ---------------------------------------------------------------------------


def test_tool_count_report_must_declare_inventory_scope(monkeypatch, tmp_path):
    """A tool-count report that lacks an inventory_scope field must FAIL, not ship a naked total.

    Guards the core rule: "Never report a tool count without the inventory scope that produced it."
    """
    # 1) the real payload always declares a valid scope
    payload = mod.build_payload(run_smoke=False)
    assert "inventory_scope" in payload and payload["inventory_scope"] in mod.INVENTORY_SCOPES

    # 2) a count without a scope is rejected by the validator ...
    naked = {"tool_count": 7, "installed_count": 3}
    with pytest.raises(ValueError, match="inventory_scope"):
        mod.require_inventory_scope(naked)

    # 3) ... and write_report refuses to persist such a report
    monkeypatch.setattr(mod, "REPORT_ROOT", tmp_path / "reports" / "deterministic-toolbox")
    with pytest.raises(ValueError, match="inventory_scope"):
        mod.write_report(naked)

    # 4) an unknown scope label is also rejected
    with pytest.raises(ValueError, match="unknown inventory_scope"):
        mod.require_inventory_scope({"tool_count": 1, "inventory_scope": "made_up_scope"})

    # 5) a capability_layer that disagrees with its scope's layer is rejected (source->authority model)
    with pytest.raises(ValueError, match="capability_layer"):
        mod.require_inventory_scope({
            "tool_count": 1,
            "inventory_scope": "repo_local_bin_tools",          # scoped_visibility
            "capability_layer": "total_installed_capability",   # wrong layer
        })

    # 6) every scope maps to a known capability layer (taxonomy is internally consistent)
    assert set(mod.SCOPE_LAYER.values()) <= set(mod.CAPABILITY_LAYERS)
    assert mod.SCOPE_LAYER["full_installed_factory_tools"] == "total_installed_capability"
    assert mod.SCOPE_LAYER["canonical_topology"] == "canonical_topology"
