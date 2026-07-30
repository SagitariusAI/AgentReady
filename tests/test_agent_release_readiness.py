from __future__ import annotations

import json
from pathlib import Path

from agent_release_readiness import build_verdict, main, write_report


def test_build_verdict_fails_on_nested_security_failure() -> None:
    verdict = build_verdict(
        [{"name": "security-scan", "exit_code": 0, "log_path": ""}],
        {"failures": 1, "timeouts": 0},
    )
    assert verdict["overall"] == "FAIL"
    assert verdict["security_failures"] == 1


def test_write_report_creates_canonical_latest_contract(tmp_path: Path) -> None:
    out = tmp_path / ".agent-reports" / "release-readiness"
    security = out / "security"
    security.mkdir(parents=True)
    (security / "security-manifest.json").write_text(
        json.dumps({"failures": 0, "timeouts": 0}),
        encoding="utf-8",
    )

    payload = write_report(
        tmp_path,
        out,
        [{"name": "security-scan", "exit_code": 0, "log_path": ""}],
    )

    assert payload["overall"] == "PASS"
    assert (out / "latest.json").exists()
    assert (out / "latest.md").exists()


def test_main_returns_only_canonical_readiness_verdict(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "agent_release_readiness.run_release_readiness",
        lambda _repo, _out: {"overall": "PASS"},
    )

    assert main(["--repo", str(tmp_path)]) == 0
