# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from agent_release_scorecard import _semgrep_scorecard_finding


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _semgrep_reports(tmp_path: Path, *, unresolved: bool = False) -> tuple[Path, dict]:
    security = tmp_path / "security"
    raw = {
        "results": [
            {"check_id": "rule.one", "path": "src/a.py", "start": {"line": 7}},
            {"check_id": "rule.two", "path": "src/a.py", "start": {"line": 7}},
        ]
    }
    raw_path = security / "semgrep.json"
    _write_json(raw_path, raw)
    raw_hash = __import__("hashlib").sha256(raw_path.read_bytes()).hexdigest()
    accepted = [
        {"rule_id": "rule.one", "path": r"src\a.py", "line": "7", "reason": "reviewed local-only path"},
    ]
    unresolved_rows = [
        {"rule_id": "rule.two", "path": "src/a.py", "line": "7"},
    ] if unresolved else []
    if not unresolved:
        accepted.append(
            {"rule_id": "rule.two", "path": "src/a.py", "line": "7", "reason": "reviewed exact line"}
        )
    _write_json(
        security / "semgrep-adjudication.json",
        {
            "schema_version": 1,
            "raw_report_sha256": raw_hash,
            "accepted": accepted,
            "unresolved": unresolved_rows,
            "accepted_count": len(accepted),
            "unresolved_count": len(unresolved_rows),
        },
    )
    return security, raw


def test_semgrep_scorecard_passes_only_complete_checksum_bound_adjudication(tmp_path: Path) -> None:
    security, raw = _semgrep_reports(tmp_path)
    finding = _semgrep_scorecard_finding(str(security), raw, [])
    assert finding["Status"] == "PASS"
    assert "accepted=2 unresolved=0" in finding["Message"]


def test_semgrep_scorecard_passes_empty_raw_report_without_adjudication(tmp_path: Path) -> None:
    security = tmp_path / "security"
    raw = {"results": []}
    _write_json(security / "semgrep.json", raw)
    finding = _semgrep_scorecard_finding(str(security), raw, [])
    assert finding["Status"] == "PASS"
    assert "no findings" in finding["Message"]


def test_semgrep_scorecard_fails_unresolved_or_missing_adjudication(tmp_path: Path) -> None:
    security, raw = _semgrep_reports(tmp_path, unresolved=True)
    assert _semgrep_scorecard_finding(str(security), raw, [])["Status"] == "FAIL"
    (security / "semgrep-adjudication.json").unlink()
    assert _semgrep_scorecard_finding(str(security), raw, [])["Status"] == "FAIL"


def test_semgrep_scorecard_fails_stale_or_identity_mismatched_adjudication(tmp_path: Path) -> None:
    security, raw = _semgrep_reports(tmp_path)
    adjudication_path = security / "semgrep-adjudication.json"
    adjudication = json.loads(adjudication_path.read_text(encoding="utf-8"))
    adjudication["raw_report_sha256"] = "0" * 64
    adjudication["accepted"][0]["rule_id"] = "invented.rule"
    _write_json(adjudication_path, adjudication)
    finding = _semgrep_scorecard_finding(str(security), raw, [])
    assert finding["Status"] == "FAIL"
    assert "checksum mismatch" in finding["Message"]
    assert "identity coverage mismatch" in finding["Message"]


def test_release_scorecard_fails_product_boundary_violations(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    reports = repo / ".agent-reports"
    for name in [
        "repo-map",
        "gap-report",
        "vault-code-separation",
        "architecture",
        "ci",
        "security",
        "sbom",
        "release-readiness",
        "product-quality",
    ]:
        (reports / name).mkdir(parents=True, exist_ok=True)

    _write_json(
        reports / "vault-code-separation" / "vault-code-separation.json",
        {
            "vault_detected": False,
            "summary": {"spec_only": 0, "partial": 0},
            "repository_boundary": {
                "protected_repo": "ExampleProject",
                "violations": [
                    {
                        "path": "docs/claim_evidence-corpus-data-foundry.md",
                        "reason": "Factory-wide data asset.",
                    }
                ],
            },
        },
    )
    (reports / "vault-code-separation" / "vault-code-separation.md").write_text(
        "# Vault/code separation\n", encoding="utf-8"
    )
    (reports / "ci" / "agent-ci-local-latest.log").write_text("EXIT pytest = 0\n", encoding="utf-8")
    _write_json(reports / "security" / "security-manifest.json", {"failures": 0, "timeouts": 0})
    _write_json(reports / "security" / "gitleaks.json", [])
    _write_json(reports / "security" / "trivy-fs.json", {"Results": []})
    _write_json(reports / "security" / "grype.json", {"matches": []})
    _write_json(reports / "security" / "semgrep.json", {"results": []})
    (reports / "sbom" / "syft.spdx.json").write_text("{}", encoding="utf-8")
    (reports / "sbom" / "syft.cyclonedx.json").write_text("{}", encoding="utf-8")
    _write_json(
        reports / "product-quality" / "product-quality.json",
        {
            "failures": 0,
            "warnings": 0,
            "passed": 1,
            "checks": [{"capability": "coverage", "message": "coverage not measured"}],
        },
    )

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_release_scorecard",
            "--repo",
            str(repo),
            "--warn-only",
        ],
        text=True,
        capture_output=True,
        timeout=60,
        env={
            **os.environ,
            "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")
            + os.pathsep
            + os.environ.get("PYTHONPATH", ""),
        },
    )

    assert proc.returncode == 0, proc.stderr or proc.stdout
    payload = json.loads((reports / "release-scorecard" / "latest.json").read_text(encoding="utf-8"))
    assert payload["overall"] == "FAIL"
    assert any(
        finding["Status"] == "FAIL"
        and finding["Area"] == "Repository boundary"
        and "ExampleProject" in finding["Message"]
        for finding in payload["findings"]
    )
