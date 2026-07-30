from __future__ import annotations

import json
import sys
from pathlib import Path

from agent_security_scan import (
    adjudicate_semgrep,
    build_steps,
    external_tool_env,
    run_security_tool,
)


def _semgrep_command(out_dir: Path, repo: Path | None) -> list[str]:
    for step in build_steps(out_dir, repo):
        if step["name"] == "semgrep":
            return [str(part) for part in step["command"]]
    raise AssertionError("no semgrep step found in build_steps")


def _trivy_command(out_dir: Path, repo: Path | None) -> list[str]:
    for step in build_steps(out_dir, repo):
        if step["name"] == "trivy":
            return [str(part) for part in step["command"]]
    raise AssertionError("no trivy step found in build_steps")


def test_run_security_tool_times_out_and_removes_stale_json(tmp_path: Path) -> None:
    stale_json = tmp_path / "tool.json"
    stale_json.write_text('{"old": true}', encoding="utf-8")
    log = tmp_path / "tool.txt"

    result = run_security_tool(
        name="slow-tool",
        command=[sys.executable, "-c", "import time; print('{'); time.sleep(5)"],
        cwd=tmp_path,
        log_path=log,
        timeout_seconds=1,
        output_paths=[stale_json],
        stdout_path=stale_json,
    )

    assert result["timed_out"] is True
    assert result["exit_code"] == 124
    assert not stale_json.exists()
    assert "TIMEOUT" in log.read_text(encoding="utf-8")


def test_build_steps_ignores_repo_wide_semgrep_rule_exclusion_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".agentready-semgrep-exclude.txt").write_text("rule.one\nrule.two\n", encoding="utf-8")
    command = _semgrep_command(tmp_path / "out", repo)

    assert "--config" in command and "auto" in command
    assert "--exclude-rule" not in command
    assert "rule.one" not in command
    assert "rule.two" not in command


def test_build_steps_has_no_exclude_rule_without_repo_or_file(tmp_path: Path) -> None:
    assert "--exclude-rule" not in _semgrep_command(tmp_path / "out", None)
    empty_repo = tmp_path / "empty"
    empty_repo.mkdir()
    assert "--exclude-rule" not in _semgrep_command(tmp_path / "out2", empty_repo)


def test_external_scanner_environment_forces_utf8(monkeypatch) -> None:
    monkeypatch.setenv("PYTHONHOME", "unsafe-runtime")
    monkeypatch.setenv("PYTHONLEGACYWINDOWSSTDIO", "1")

    env = external_tool_env()

    assert "PYTHONHOME" not in env
    assert "PYTHONLEGACYWINDOWSSTDIO" not in env
    assert env["PYTHONUTF8"] == "1"


def test_gitleaks_uses_repo_config_and_skips_generated_bytecode(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    config = repo / ".gitleaks.toml"
    config.write_text("[extend]\nuseDefault = true\n", encoding="utf-8")
    command = next(step["command"] for step in build_steps(tmp_path / "out", repo)
                   if step["name"] == "gitleaks")
    assert command[command.index("--config") + 1] == str(config)
    assert "__pycache__" in next(step["command"] for step in build_steps(tmp_path / "out", repo)
                                 if step["name"] == "semgrep")


def test_trivy_excludes_nested_generated_bytecode_without_rule_suppression(tmp_path: Path) -> None:
    command = _trivy_command(tmp_path / "out", tmp_path)
    assert ["--skip-dirs", "**/__pycache__"] == command[
        command.index("**/__pycache__") - 1:command.index("**/__pycache__") + 1
    ]
    assert "**/*.pyc" in command
    assert "**/*.pyo" in command
    assert "--skip-files" in command


def test_semgrep_adjudication_requires_local_http_or_explicit_urllib_review(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src/local.py").write_text(
        'requests.get("http://192.0.2.4:8080/x")\n', encoding="utf-8"
    )
    (repo / "src/public.py").write_text(
        'requests.get("http://example.com/x")\n', encoding="utf-8"
    )
    (repo / "src/reviewed.py").write_text(
        "urllib.request.urlopen(req)  # nosec B310\n", encoding="utf-8"
    )
    (repo / "src/eval.py").write_text("eval(user_input)\n", encoding="utf-8")
    report = tmp_path / "semgrep.json"
    report.write_text(json.dumps({"results": [
        {"check_id": "python.lang.security.audit.insecure-transport.requests",
         "path": "src/local.py", "start": {"line": 1}},
        {"check_id": "python.lang.security.audit.insecure-transport.requests",
         "path": "src/public.py", "start": {"line": 1}},
        {"check_id": "python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected",
         "path": "src/reviewed.py", "start": {"line": 1}},
        {"check_id": "python.lang.security.audit.eval",
         "path": "src/eval.py", "start": {"line": 1}},
    ]}), encoding="utf-8")
    result = adjudicate_semgrep(repo, report)
    assert result["schema_version"] == 1
    assert len(result["raw_report_sha256"]) == 64
    assert result["accepted_count"] == 2
    assert result["unresolved_count"] == 2
