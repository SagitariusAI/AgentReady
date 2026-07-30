"""Release scorecard -- Python port of `bin/agent-release-scorecard.ps1` (PS->Python Phase 4, SHADOW).

The release **PASS/WARN/FAIL authority**: aggregates the Factory evidence reports into an ordered list of
findings and a final verdict. PowerShell stays authoritative until the flip. This module reproduces the
durable logic byte-faithfully:

- the ordered checks (semgrep-exclude → git → 8 required report dirs → vault/code → CI log → security
  manifest/gitleaks/trivy/grype/semgrep → SBOM → product-quality → production-maturity → packaging),
- the finding schema `{Status, Area, Message, Evidence}` and the exact messages,
- the verdict (FAIL if any FAIL, else WARN if any WARN, else PASS),
- the exit code (FAIL 2 / WARN 1 / PASS 0, all suppressed to 0 by `-WarnOnly`),
- the JSON `{repo, generated_at, overall, failures, warnings, findings}` + the MD table,
- degraded behavior: a missing report file is None (often FAIL/WARN); an INVALID json adds a
  `FAIL 'Report parsing'` finding inline; the production-maturity FAIL is deliberately WARN (advisory, to
  avoid a circular release-scorecard dependency).

`--shadow` computes the Python verdict and writes a comparison vs the authoritative scorecard to
`.agent-reports/release-scorecard/shadow/` WITHOUT overwriting the real scorecard (no wrapper flip yet).
Parity proven in `smoke/agent_release_scorecard_shadow_smoke.py`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from collections import Counter
from datetime import datetime
from pathlib import Path

AGENTREADY_HOME = Path(os.environ.get("AGENTREADY_HOME") or Path(__file__).resolve().parents[1])


def _finding(status: str, area: str, message: str, evidence: str = "") -> dict:
    return {"Status": status, "Area": area, "Message": message, "Evidence": evidence}


def count_array(value) -> int:
    """Port of PS Count-Array: None->0, list->len, scalar/object->1."""
    if value is None:
        return 0
    if isinstance(value, list):
        return len(value)
    return 1


def _ps_truthy(value) -> bool:
    """Replicate PowerShell `if ($null -ne $x)` on a ConvertFrom-Json result.

    PS array semantics make `$null -ne @()` *falsy*, so PowerShell SKIPS a block whose JSON parsed to an
    empty array (e.g. an empty `gitleaks.json` `[]`). An object (even `{}`) or a non-empty array is truthy.
    Matching this exactly keeps the findings list byte-identical to PowerShell.
    """
    if value is None:
        return False
    if isinstance(value, list):
        return len(value) > 0
    return True


def _read_json(path: str, findings: list[dict]):
    """Port of Read-JsonFile: missing->None; invalid->append FAIL 'Report parsing' + None."""
    if not os.path.exists(path):
        return None
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        findings.append(_finding("FAIL", "Report parsing", f"Invalid JSON: {path}", path))
        return None


def _semgrep_identity(row: dict, *, adjudicated: bool) -> tuple[str, str, int]:
    rule_key = "rule_id" if adjudicated else "check_id"
    rule = str(row.get(rule_key) or "")
    path = str(row.get("path") or "").replace("\\", "/").lower()
    raw_line = row.get("line") if adjudicated else (
        (row.get("start") or {}).get("line") if isinstance(row.get("start"), dict) else 0
    )
    try:
        line = int(raw_line or 0)
    except (TypeError, ValueError):
        line = 0
    return rule, path, line


def _semgrep_scorecard_finding(security_dir: str, semgrep: dict, findings: list[dict]) -> dict:
    """Require adjudication to cover the exact raw Semgrep report.

    Raw findings are never silently downgraded. A non-empty report passes only
    when a schema-v1 adjudication is cryptographically tied to that report,
    covers every finding identity exactly once, carries a reason for every
    accepted row, and leaves zero unresolved rows.
    """
    raw_path = os.path.join(security_dir, "semgrep.json")
    adjudication_path = os.path.join(security_dir, "semgrep-adjudication.json")
    raw_results = semgrep.get("results")
    if not isinstance(raw_results, list):
        return _finding("FAIL", "Static analysis", "Semgrep results are missing or invalid.", raw_path)
    raw_count = len(raw_results)
    if raw_count == 0:
        return _finding("PASS", "Static analysis", "Semgrep reported no findings.", raw_path)

    adjudication = _read_json(adjudication_path, findings)
    evidence = f"{raw_path}; {adjudication_path}"
    if not isinstance(adjudication, dict):
        return _finding(
            "FAIL", "Static analysis",
            f"Semgrep reported {raw_count} raw findings without a valid adjudication.", evidence,
        )

    issues: list[str] = []
    if adjudication.get("schema_version") != 1:
        issues.append("unsupported adjudication schema")
    try:
        raw_sha256 = hashlib.sha256(Path(raw_path).read_bytes()).hexdigest()
    except OSError:
        raw_sha256 = ""
    if not raw_sha256 or adjudication.get("raw_report_sha256") != raw_sha256:
        issues.append("raw report checksum mismatch")

    accepted = adjudication.get("accepted")
    unresolved = adjudication.get("unresolved")
    if not isinstance(accepted, list) or not isinstance(unresolved, list):
        issues.append("accepted/unresolved rows are invalid")
        accepted = accepted if isinstance(accepted, list) else []
        unresolved = unresolved if isinstance(unresolved, list) else []
    try:
        accepted_count = int(adjudication.get("accepted_count", -1))
        unresolved_count = int(adjudication.get("unresolved_count", -1))
    except (TypeError, ValueError):
        accepted_count = -1
        unresolved_count = -1
        issues.append("declared adjudication counts are invalid")
    if accepted_count != len(accepted):
        issues.append("accepted count mismatch")
    if unresolved_count != len(unresolved):
        issues.append("unresolved count mismatch")
    if len(accepted) + len(unresolved) != raw_count:
        issues.append("adjudication total does not equal raw findings")
    if any(not str(row.get("reason") or "").strip() for row in accepted if isinstance(row, dict)):
        issues.append("accepted finding lacks an evidence reason")

    raw_identities = Counter(
        _semgrep_identity(row, adjudicated=False) for row in raw_results if isinstance(row, dict)
    )
    adjudicated_rows = [row for row in accepted + unresolved if isinstance(row, dict)]
    adjudicated_identities = Counter(
        _semgrep_identity(row, adjudicated=True) for row in adjudicated_rows
    )
    if sum(raw_identities.values()) != raw_count or len(adjudicated_rows) != raw_count:
        issues.append("finding rows are malformed")
    if any(not rule or not path or line <= 0 for rule, path, line in raw_identities):
        issues.append("raw finding identity is incomplete")
    if any(not rule or not path or line <= 0 for rule, path, line in adjudicated_identities):
        issues.append("adjudicated finding identity is incomplete")
    if raw_identities != adjudicated_identities:
        issues.append("finding identity coverage mismatch")

    if issues:
        return _finding(
            "FAIL", "Static analysis",
            f"Semgrep adjudication is invalid for {raw_count} raw findings: {'; '.join(issues)}.", evidence,
        )
    if unresolved:
        return _finding(
            "FAIL", "Static analysis",
            f"Semgrep adjudication leaves {len(unresolved)} of {raw_count} findings unresolved.", evidence,
        )
    return _finding(
        "PASS", "Static analysis",
        f"Semgrep reported {raw_count} raw findings; accepted={len(accepted)} unresolved=0 "
        "after explicit adjudication.", evidence,
    )


def _git_dirty(repo: str) -> str:
    try:
        out = subprocess.run(["git", "-C", repo, "status", "--short"], capture_output=True, text=True,
                             timeout=30, check=False)
        return out.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _maturity_path() -> str:
    return str(AGENTREADY_HOME / "reports" / "production-maturity" / "latest.json")


def collect_findings(repo: str, *, allow_dirty: bool = False) -> list[dict]:
    """Build the ordered findings list, byte-faithful to agent-release-scorecard.ps1 L51-254."""
    repo = str(repo)
    reports = os.path.join(repo, ".agent-reports")
    findings: list[dict] = []

    semgrep_exclude = os.path.join(repo, ".agentready-semgrep-exclude.txt")
    if os.path.exists(semgrep_exclude):
        findings.append(_finding("FAIL", "Static analysis governance",
                                 "Repo-wide Semgrep rule exclusion files are forbidden for release "
                                 "readiness; remove the file and resolve or explicitly adjudicate findings "
                                 "in code review.", semgrep_exclude))

    dirty = _git_dirty(repo)
    if dirty and not allow_dirty:
        findings.append(_finding("WARN", "Git", "Working tree has uncommitted changes.", "git status --short"))
    else:
        findings.append(_finding("PASS", "Git", "Working tree cleanliness checked.", "git status --short"))

    for area, sub in (("Repo map", "repo-map"), ("Gap report", "gap-report"),
                      ("Vault/code separation", "vault-code-separation"), ("Architecture", "architecture"),
                      ("CI", "ci"), ("Security", "security"), ("SBOM", "sbom"),
                      ("Release readiness", "release-readiness")):
        path = os.path.join(reports, sub)
        if os.path.exists(path):
            findings.append(_finding("PASS", area, "Expected report path exists.", path))
        else:
            findings.append(_finding("FAIL", area, "Expected report path is missing.", path))

    readiness_path = os.path.join(reports, "release-readiness", "latest.json")
    readiness = _read_json(readiness_path, findings)
    if readiness is None:
        findings.append(_finding(
            "FAIL",
            "Release readiness",
            "Canonical release-readiness verdict is missing or invalid.",
            readiness_path,
        ))
    else:
        readiness_overall = str(readiness.get("overall") or "").upper()
        if readiness_overall != "PASS":
            findings.append(_finding(
                "FAIL",
                "Release readiness",
                "Canonical release-readiness verdict is not PASS "
                f"(overall={readiness_overall or 'MISSING'}, "
                f"failed_checks={int(readiness.get('failed_checks') or 0)}, "
                f"security_failures={int(readiness.get('security_failures') or 0)}, "
                f"security_timeouts={int(readiness.get('security_timeouts') or 0)}).",
                readiness_path,
            ))
        else:
            findings.append(_finding(
                "PASS",
                "Release readiness",
                "Canonical release-readiness verdict is PASS.",
                readiness_path,
            ))

    vault_code = _read_json(os.path.join(reports, "vault-code-separation", "vault-code-separation.json"),
                            findings)
    if isinstance(vault_code, dict) and _ps_truthy(vault_code):
        vc_md = os.path.join(reports, "vault-code-separation", "vault-code-separation.md")
        boundary = vault_code.get("repository_boundary")
        boundary_violations = count_array(boundary.get("violations")) if isinstance(boundary, dict) else 0
        if boundary_violations > 0:
            protected_repo = (
                str(boundary.get("protected_repo") or "")
                if isinstance(boundary, dict)
                else ""
            ) or "protected product repo"
            findings.append(_finding("FAIL", "Repository boundary",
                                     f"{protected_repo} has {boundary_violations} product-boundary "
                                     "violation(s); move Factory-wide assets out of the product repo before "
                                     "release.", vc_md))
        if vault_code.get("vault_detected"):
            summary = vault_code.get("summary") or {}
            spec_only = int(summary.get("spec_only") or 0)
            partial = int(summary.get("partial") or 0)
            findings.append(_finding(
                "PASS",
                "Vault/code separation",
                "Vault/spec corpus is explicitly classified and has no repository-boundary violations. "
                f"Non-completion states remain visible: spec_only={spec_only} partial={partial}.",
                vc_md,
            ))
        else:
            findings.append(_finding("PASS", "Vault/code separation",
                                     "No mature vault/spec corpus detected by the separation scanner.", vc_md))

    ci_log = os.path.join(reports, "ci", "agent-ci-local-latest.log")
    if os.path.exists(ci_log):
        ci_text = Path(ci_log).read_text(encoding="utf-8", errors="replace")
        bad_exit = re.findall(r"EXIT\s+(.+?)\s+=\s+([1-9]\d*)", ci_text)
        errors = re.findall(r"^ERROR\s+(.+?)\s+=", ci_text, re.MULTILINE)
        if bad_exit or errors:
            findings.append(_finding("FAIL", "CI",
                                     f"Local CI reported {len(bad_exit)} nonzero exits and {len(errors)} "
                                     "errors.", ci_log))
        else:
            findings.append(_finding("PASS", "CI", "Local CI log has no recorded nonzero exits.", ci_log))
    else:
        findings.append(_finding("FAIL", "CI", "Local CI latest log is missing.", ci_log))

    security_dir = os.path.join(reports, "security")
    manifest = _read_json(os.path.join(security_dir, "security-manifest.json"), findings)
    if isinstance(manifest, dict) and _ps_truthy(manifest):
        sec_failures = int(manifest.get("failures") or 0)
        sec_timeouts = int(manifest.get("timeouts") or 0)
        ev = os.path.join(security_dir, "security-manifest.json")
        if sec_failures or sec_timeouts:
            findings.append(_finding("FAIL", "Security scan",
                                     f"Security manifest reports failures={sec_failures} "
                                     f"timeouts={sec_timeouts}.", ev))
        else:
            findings.append(_finding("PASS", "Security scan",
                                     "Security manifest reports all configured tools completed successfully.",
                                     ev))

    gitleaks = _read_json(os.path.join(security_dir, "gitleaks.json"), findings)
    if _ps_truthy(gitleaks):
        ev = os.path.join(security_dir, "gitleaks.json")
        count = count_array(gitleaks)
        if count > 0:
            findings.append(_finding("FAIL", "Secrets", f"Gitleaks reported {count} findings.", ev))
        else:
            findings.append(_finding("PASS", "Secrets", "Gitleaks reported no findings.", ev))

    trivy = _read_json(os.path.join(security_dir, "trivy-fs.json"), findings)
    if isinstance(trivy, dict) and _ps_truthy(trivy):
        ev = os.path.join(security_dir, "trivy-fs.json")
        critical = high = secret_count = 0
        for r in (trivy.get("Results") or []):
            for v in (r.get("Vulnerabilities") or []):
                if v.get("Severity") == "CRITICAL":
                    critical += 1
                if v.get("Severity") == "HIGH":
                    high += 1
            if "Secrets" in r:
                secret_count += count_array(r.get("Secrets"))
        if critical or high or secret_count:
            findings.append(_finding("FAIL", "Security",
                                     f"Trivy reported critical={critical} high={high} "
                                     f"secrets={secret_count}.", ev))
        else:
            findings.append(_finding("PASS", "Security",
                                     "Trivy reported no high/critical vulnerability or secret findings.", ev))

    grype = _read_json(os.path.join(security_dir, "grype.json"), findings)
    if isinstance(grype, dict) and _ps_truthy(grype):
        ev = os.path.join(security_dir, "grype.json")
        critical = high = 0
        for m in (grype.get("matches") or []):
            sev = ((m.get("vulnerability") or {}).get("severity"))
            if sev == "Critical":
                critical += 1
            if sev == "High":
                high += 1
        if critical or high:
            findings.append(_finding("FAIL", "Security",
                                     f"Grype reported critical={critical} high={high} vulnerabilities.", ev))
        else:
            findings.append(_finding("PASS", "Security", "Grype reported no high/critical vulnerability "
                                     "findings.", ev))

    semgrep = _read_json(os.path.join(security_dir, "semgrep.json"), findings)
    if isinstance(semgrep, dict) and _ps_truthy(semgrep):
        findings.append(_semgrep_scorecard_finding(security_dir, semgrep, findings))

    sbom_dir = os.path.join(reports, "sbom")
    syft = os.path.join(sbom_dir, "syft.spdx.json")
    cdx = next((c for c in (os.path.join(sbom_dir, "syft.cyclonedx.json"),
                            os.path.join(sbom_dir, "cdxgen.cdx.json")) if os.path.exists(c)), None)
    cdx_validate = os.path.join(sbom_dir, "cyclonedx-validate.txt")
    if os.path.exists(syft) and cdx:
        findings.append(_finding("PASS", "SBOM", "Syft SPDX and CycloneDX SBOM files exist.", sbom_dir))
    else:
        findings.append(_finding("FAIL", "SBOM", "Missing Syft SPDX or CycloneDX SBOM output.", sbom_dir))
    if os.path.exists(cdx_validate):
        validate_text = Path(cdx_validate).read_text(encoding="utf-8", errors="replace")
        if re.search(r"invalid|error|failed", validate_text):
            findings.append(_finding("FAIL", "SBOM", "CycloneDX validation appears to have failed.",
                                     cdx_validate))
        else:
            findings.append(_finding("PASS", "SBOM", "CycloneDX validation output exists without obvious "
                                     "failure markers.", cdx_validate))

    pq_dir = os.path.join(reports, "product-quality")
    pq = _read_json(os.path.join(pq_dir, "product-quality.json"), findings)
    if pq is None:
        findings.append(_finding("WARN", "Product quality",
                                 "No product-quality evidence (run agent-product-quality).", pq_dir))
    else:
        pq_md = os.path.join(pq_dir, "product-quality.md")
        cov = [c for c in (pq.get("checks") or []) if c.get("capability") == "coverage"]
        cov_msg = cov[0].get("message") if cov else "coverage not measured"
        if int(pq.get("failures") or 0) > 0:
            findings.append(_finding("FAIL", "Product quality",
                                     f"Product-quality checks failed ({pq.get('failures')}). {cov_msg}", pq_md))
        elif int(pq.get("passed") or 0) == 0:
            findings.append(_finding("WARN", "Product quality",
                                     "Product-quality ran but measured nothing (all checks skipped).", pq_md))
        elif int(pq.get("warnings") or 0) > 0:
            findings.append(_finding("WARN", "Product quality",
                                     f"Product-quality has warnings. {cov_msg}", pq_md))
        else:
            findings.append(_finding("PASS", "Product quality", f"Product-quality passed. {cov_msg}", pq_md))

    maturity_path = _maturity_path()
    maturity = _read_json(maturity_path, findings)
    if maturity is None:
        findings.append(_finding("WARN", "Production maturity",
                                 "Production-maturity board is missing; run agent-production-maturity.",
                                 maturity_path))
    else:
        maturity_md = str(AGENTREADY_HOME / "reports" / "production-maturity" / "latest.md")
        overall = str(maturity.get("overall") or "")
        score_val = int(maturity.get("maturity_score") or 0)
        if overall == "FAIL":
            findings.append(_finding("WARN", "Production maturity",
                                     f"Production-maturity board reports blocking failures; score={score_val}. "
                                     "This is advisory to avoid circular release-scorecard dependency; inspect "
                                     "before founder handoff.", maturity_md))
        else:
            findings.append(_finding("PASS", "Production maturity",
                                     f"Production-maturity board is present; overall={overall} "
                                     f"score={score_val}. Advisory warnings are tracked backlog.", maturity_md))

    artifact_evidence = next((c for c in (os.path.join(reports, "package", "artifacts.txt"),
                                          os.path.join(reports, "package-windows", "artifacts.txt"))
                              if os.path.exists(c)), None)
    if artifact_evidence:
        artifact_text = Path(artifact_evidence).read_text(encoding="utf-8", errors="replace")
        if re.search(r"\.(exe|msi|zip|nupkg|whl)\b", artifact_text):
            findings.append(_finding("PASS", "Packaging", "Package artifacts were found.", artifact_evidence))
        else:
            findings.append(_finding("WARN", "Packaging",
                                     "Package report exists, but no final distributable artifact is listed.",
                                     artifact_evidence))
    else:
        findings.append(_finding("WARN", "Packaging",
                                 "Package artifact report is missing or packaging is not configured for this "
                                 "stack repo.", ".agent-reports\\package-windows\\artifacts.txt"))
    return findings


def decide(findings: list[dict]) -> dict:
    fail = sum(1 for f in findings if f["Status"] == "FAIL")
    warn = sum(1 for f in findings if f["Status"] == "WARN")
    overall = "FAIL" if fail > 0 else ("WARN" if warn > 0 else "PASS")
    return {"overall": overall, "failures": fail, "warnings": warn}


def exit_code(overall: str, warn_only: bool) -> int:
    if warn_only:
        return 0
    if overall == "FAIL":
        return 2
    if overall == "WARN":
        return 1
    return 0


def build_score(repo: str, allow_dirty: bool = False) -> dict:
    findings = collect_findings(repo, allow_dirty=allow_dirty)
    verdict = decide(findings)
    return {"repo": str(repo), "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "overall": verdict["overall"], "failures": verdict["failures"],
            "warnings": verdict["warnings"], "findings": findings}


def render_md(score: dict) -> str:
    lines = ["# Agent Release Scorecard", "",
             f"- Repo: {score['repo']}",
             f"- Generated: {score['generated_at']}",
             f"- Overall: {score['overall']}",
             f"- Failures: {score['failures']}",
             f"- Warnings: {score['warnings']}", "",
             "| Status | Area | Message | Evidence |", "| --- | --- | --- | --- |"]
    for f in score["findings"]:
        msg = f["Message"].replace("|", "/")
        ev = f["Evidence"].replace("|", "/")
        lines.append(f"| {f['Status']} | {f['Area']} | {msg} | {ev} |")
    return "\n".join(lines)


def _write(out_dir: str, score: dict) -> tuple[str, str]:
    os.makedirs(out_dir, exist_ok=True)
    json_path = os.path.join(out_dir, "scorecard.json")
    md_path = os.path.join(out_dir, "scorecard.md")
    payload = json.dumps(score, indent=2, ensure_ascii=True)
    Path(json_path).write_text(payload, encoding="utf-8")
    Path(os.path.join(out_dir, "latest.json")).write_text(payload, encoding="utf-8")
    md = render_md(score)
    Path(md_path).write_text(md, encoding="utf-8")
    Path(os.path.join(out_dir, "latest.md")).write_text(md, encoding="utf-8")
    return json_path, md_path


def run(repo: str, out_dir: str = "", allow_dirty: bool = False, warn_only: bool = False, *,
        echo: bool = True, write_outputs: bool = True) -> dict:
    out_dir = out_dir or os.path.join(repo, ".agent-reports", "release-scorecard")
    score = build_score(repo, allow_dirty=allow_dirty)
    code = exit_code(score["overall"], warn_only)
    md_path = os.path.join(out_dir, "scorecard.md")
    if write_outputs:
        _, md_path = _write(out_dir, score)
    if echo:
        print(f"Agent release scorecard: {score['overall']} ({score['failures']} fail, "
              f"{score['warnings']} warn)")
        print(md_path)
    return {**score, "exit_code": code, "md_path": md_path}


def shadow(repo: str, allow_dirty: bool = False, warn_only: bool = False) -> int:
    score = build_score(repo, allow_dirty=allow_dirty)
    verdict = {k: score[k] for k in ("overall", "failures", "warnings")}
    out_dir = os.path.join(repo, ".agent-reports", "release-scorecard")
    auth_path = os.path.join(out_dir, "latest.json")
    auth = None
    if os.path.exists(auth_path):
        try:
            auth = json.loads(Path(auth_path).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            auth = None
    agrees = bool(auth) and all(auth.get(k) == verdict[k] for k in ("overall", "failures", "warnings"))
    comparison = {"at": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                  "python": {**verdict, "exit_code": exit_code(score["overall"], warn_only),
                             "findings": score["findings"]},
                  "authoritative": auth and {k: auth.get(k) for k in ("overall", "failures", "warnings")},
                  "agrees": agrees}
    shadow_dir = os.path.join(out_dir, "shadow")
    os.makedirs(shadow_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(shadow_dir, f"scorecard-shadow-{stamp}.json")
    Path(out).write_text(json.dumps(comparison, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"Agent release scorecard SHADOW: {out} (agrees={agrees})")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser("agent_release_scorecard")
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--allow-dirty", action="store_true")
    parser.add_argument("--warn-only", action="store_true")
    parser.add_argument("--shadow", action="store_true",
                        help="compute the Python verdict + comparison; do NOT write the authoritative scorecard")
    args = parser.parse_args(argv)
    repo = str(Path(args.repo).resolve())
    if args.shadow:
        return shadow(repo, allow_dirty=args.allow_dirty, warn_only=args.warn_only)
    return run(repo, args.out_dir, args.allow_dirty, args.warn_only)["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
