# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Public support for test agent release scorecard module."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import agent_release_scorecard as sc


def test_count_array():
    assert sc.count_array(None) == 0
    assert sc.count_array([]) == 0
    assert sc.count_array([1, 2, 3]) == 3
    assert sc.count_array({"a": 1}) == 1
    assert sc.count_array(5) == 1


def test_ps_truthy_empty_array_is_falsy():

    assert sc._ps_truthy(None) is False
    assert sc._ps_truthy([]) is False
    assert sc._ps_truthy([1]) is True
    assert sc._ps_truthy({}) is True
    assert sc._ps_truthy({"a": 1}) is True


def test_decide():
    assert sc.decide([{"Status": "PASS"}])["overall"] == "PASS"
    assert sc.decide([{"Status": "PASS"}, {"Status": "WARN"}]) == {"overall": "WARN", "failures": 0, "warnings": 1}
    assert sc.decide([{"Status": "WARN"}, {"Status": "FAIL"}]) == {"overall": "FAIL", "failures": 1, "warnings": 1}


def test_exit_code():
    assert sc.exit_code("FAIL", False) == 2
    assert sc.exit_code("WARN", False) == 1
    assert sc.exit_code("PASS", False) == 0
    assert all(sc.exit_code(v, True) == 0 for v in ("FAIL", "WARN", "PASS"))


@pytest.fixture()
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(sc, "AGENTREADY_HOME", tmp_path / "home")
    return tmp_path / "repo"


def _w(root: Path, rel: str, content: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_empty_gitleaks_is_skipped(repo):
    _w(repo, ".agent-reports/security/gitleaks.json", "[]")  # empty array -> PS skips -> no Secrets finding
    findings = sc.collect_findings(str(repo))
    assert not any(f["Area"] == "Secrets" for f in findings)


def test_gitleaks_with_findings_fails(repo):
    _w(repo, ".agent-reports/security/gitleaks.json", json.dumps([{"x": 1}, {"y": 2}]))
    secrets = [f for f in sc.collect_findings(str(repo)) if f["Area"] == "Secrets"]
    assert secrets and secrets[0]["Status"] == "FAIL" and "2 findings" in secrets[0]["Message"]


def test_trivy_critical_fails(repo):
    _w(repo, ".agent-reports/security/trivy-fs.json",
       json.dumps({"Results": [{"Vulnerabilities": [{"Severity": "CRITICAL"}, {"Severity": "HIGH"}]}]}))
    sec = [f for f in sc.collect_findings(str(repo)) if f["Area"] == "Security" and f["Status"] == "FAIL"]
    assert sec and "critical=1 high=1" in sec[0]["Message"]


def test_boundary_violation_fails(repo):
    _w(repo, ".agent-reports/vault-code-separation/vault-code-separation.json",
       json.dumps({"vault_detected": False, "repository_boundary": {
           "protected_repo": "ExampleProject", "violations": [{"path": "x"}]}}))
    rb = [f for f in sc.collect_findings(str(repo)) if f["Area"] == "Repository boundary"]
    assert rb and rb[0]["Status"] == "FAIL" and "ExampleProject has 1 product-boundary" in rb[0]["Message"]


def test_classified_vault_without_boundary_violations_is_nonblocking(repo):
    _w(
        repo,
        ".agent-reports/vault-code-separation/vault-code-separation.json",
        json.dumps({
            "vault_detected": True,
            "summary": {"spec_only": 4, "partial": 2},
            "repository_boundary": {"protected_repo": None, "violations": []},
        }),
    )

    vault = [
        f
        for f in sc.collect_findings(str(repo))
        if f["Area"] == "Vault/code separation" and "spec_only=" in f["Message"]
    ]

    assert vault and vault[0]["Status"] == "PASS"
    assert "spec_only=4 partial=2" in vault[0]["Message"]


def test_production_maturity_fail_is_advisory_warn(repo, monkeypatch):
    home = repo.parent / "home"
    monkeypatch.setattr(sc, "AGENTREADY_HOME", home)
    _w(home, "reports/production-maturity/latest.json", json.dumps({"overall": "FAIL", "maturity_score": 5}))
    pm = [f for f in sc.collect_findings(str(repo)) if f["Area"] == "Production maturity"]
    assert pm and pm[0]["Status"] == "WARN"  # FAIL downgraded to WARN to avoid circular dependency


def test_semgrep_exclude_file_fails(repo):
    _w(repo, ".agentready-semgrep-exclude.txt", "rules\n")
    findings = sc.collect_findings(str(repo))
    assert findings[0]["Area"] == "Static analysis governance" and findings[0]["Status"] == "FAIL"


def test_invalid_json_adds_parse_fail(repo):
    _w(repo, ".agent-reports/security/gitleaks.json", "{not json")
    assert any(f["Area"] == "Report parsing" and f["Status"] == "FAIL" for f in sc.collect_findings(str(repo)))


def test_all_missing_is_fail(repo):
    repo.mkdir(parents=True)
    score = sc.build_score(str(repo))
    assert score["overall"] == "FAIL"  # 8 missing report dirs + missing CI/SBOM
    assert score["failures"] >= 10


def test_nested_release_security_failure_cannot_be_masked_by_top_level_pass(repo):
    _w(
        repo,
        ".agent-reports/security/security-manifest.json",
        json.dumps({"failures": 0, "timeouts": 0}),
    )
    _w(
        repo,
        ".agent-reports/release-readiness/latest.json",
        json.dumps({
            "overall": "FAIL",
            "failed_checks": 0,
            "security_failures": 1,
            "security_timeouts": 0,
        }),
    )

    findings = sc.collect_findings(str(repo))

    nested = [
        finding for finding in findings
        if finding["Area"] == "Release readiness"
        and "Canonical release-readiness verdict is not PASS" in finding["Message"]
    ]
    assert nested and nested[0]["Status"] == "FAIL"
