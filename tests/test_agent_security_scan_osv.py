"""osv-scanner invocation contract for the AgentReady security scan.

The remote deps.dev transitive resolver can fail with internal errors after the
local direct-package findings are already resolved, so the source scan runs with
``--no-resolve`` against repo lockfiles/manifests (the release evidence). Lock
that into a test so the flag is not silently dropped.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import agent_security_scan as ss  # noqa: E402


def _osv_command(tmp_path):
    steps = ss.build_steps(tmp_path)
    for step in steps:
        cmd = step.get("command") or []
        if cmd and cmd[0] == "osv-scanner":
            return cmd
    raise AssertionError("no osv-scanner step found in build_steps")


def _osv_step(out_dir, repo):
    for step in ss.build_steps(out_dir, repo):
        if step.get("name") == "osv-scanner":
            return step
    raise AssertionError("no osv-scanner step found in build_steps")


def _tool_command(tmp_path, tool):
    for step in ss.build_steps(tmp_path):
        cmd = step.get("command") or []
        if cmd and cmd[0] == tool:
            return cmd
    raise AssertionError(f"no {tool} step found in build_steps")


def test_osv_source_scan_uses_no_resolve(tmp_path):
    cmd = _osv_command(tmp_path)
    assert "scan" in cmd and "source" in cmd, f"expected an osv source scan: {cmd}"
    assert "--no-resolve" in cmd, f"osv-scanner must pass --no-resolve: {cmd}"
    assert "--format" in cmd and "json" in cmd, f"osv-scanner must emit json: {cmd}"


def test_osv_uses_explicit_nested_lockfile_on_windows_safe_path(tmp_path):
    repo = tmp_path / "repo"
    lockfile = repo / "web" / "package-lock.json"
    lockfile.parent.mkdir(parents=True)
    lockfile.write_text("{}", encoding="utf-8")
    ignored = repo / "node_modules" / "package-lock.json"
    ignored.parent.mkdir()
    ignored.write_text("{}", encoding="utf-8")

    step = _osv_step(tmp_path / "out", repo)
    cmd = step["command"]

    assert step["skip_reason"] == ""
    assert "-r" not in cmd and "--recursive" not in cmd
    assert cmd.count("--lockfile") == 1
    assert str(lockfile) in cmd
    assert str(ignored) not in cmd


def test_osv_includes_requirements_and_tolerates_empty_lockfile_stub(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "uv.lock").write_text("", encoding="utf-8")
    requirements = repo / "requirements-dev.txt"
    requirements.write_text("pytest==8.4.1\n", encoding="utf-8")

    step = _osv_step(tmp_path / "out", repo)
    cmd = step["command"]

    assert "--allow-no-lockfiles" in cmd
    assert str(requirements) in cmd
    assert cmd.count("--lockfile") == 2


def test_osv_cleanly_skips_repo_without_supported_lockfiles(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    step = _osv_step(tmp_path / "out", repo)

    assert step["skip_reason"] == "no supported dependency lockfiles found"


def test_osv_prunes_nested_generated_mirrors_and_scip_sources(tmp_path):
    repo = tmp_path / "repo"
    mirror = repo / "code-graph" / "mirrors" / "studio"
    scip = repo / "src" / "scip" / "bindings" / "go"
    mirror.mkdir(parents=True)
    scip.mkdir(parents=True)
    (mirror / "requirements.txt").write_text("requests==2.0\n", encoding="utf-8")
    (scip / "go.mod").write_text("module example\n", encoding="utf-8")
    root_requirements = repo / "requirements.txt"
    root_requirements.write_text("pytest==8.4.1\n", encoding="utf-8")

    discovered = ss.discover_osv_lockfiles(repo)

    assert discovered == [root_requirements]


def test_grype_excludes_local_untracked_scip_binaries(tmp_path):
    step = next(item for item in ss.build_steps(tmp_path) if item["name"] == "grype")
    command = step["command"]

    assert "./bin/scip.exe" in command
    assert "./bin/scip-python.exe" in command
    assert "./bin/scip-typescript.exe" in command


def test_trivy_has_an_explicit_timeout(tmp_path):
    # The default 5m deadline times out on the misconfig/helm analyzer for large
    # repos, failing the whole scan. Lock in an explicit higher timeout.
    cmd = _tool_command(tmp_path, "trivy")
    assert "--timeout" in cmd, f"trivy must pass an explicit --timeout: {cmd}"
