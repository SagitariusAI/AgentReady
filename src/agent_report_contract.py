# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

AGENTREADY_HOME = Path(os.environ.get("AGENTREADY_HOME") or Path(__file__).resolve().parents[1])

SURFACE_PRIMARY_PATTERNS: dict[str, list[str]] = {
    "repo-map": [
        "directory-summary.md",
        "file-inventory.json",
        "repomix.md",
        "code2prompt.md",
        "cloc.json",
        "tokei.json",
        "tags.jsonl",
    ],
    "gap-report": ["gap-summary.json", "pytest.txt", "ruff.txt", "*.json", "*.md", "*.txt"],
    "architecture": ["pydeps.txt", "dependency-cruiser.json", "madge.json", "*.md", "*.txt", "*.json"],
    "ci": ["agent-ci-local-latest.log", "agent-ci-local-*.log", "*.log", "*.txt"],
    "python-quality": ["python-quality.json", "ruff.txt", "vulture.txt", "radon_cc.txt", "*.json", "*.txt"],
    "security": ["security-manifest.json", "gitleaks.json", "trivy-fs.json", "osv-scanner.json", "*.json", "*.txt"],
    "sbom": ["cyclonedx.json", "sbom.cdx.json", "*.json", "*.spdx", "*.txt"],
    "release-readiness": ["release-readiness.json", "*.md", "*.json", "*.txt"],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def normalize_report(
    repo: Path,
    surface: str,
    report_dir: Path,
    primary: Path | None,
    status: str,
    summary: str,
) -> Path:
    report_dir.mkdir(parents=True, exist_ok=True)
    files = sorted(p.name for p in report_dir.iterdir() if p.is_file())
    primary_path = primary if primary and primary.exists() else None
    latest_md = report_dir / "latest.md"
    latest_json = report_dir / "latest.json"
    generated = now_iso()

    payload = {
        "generated_at": generated,
        "repo": str(repo),
        "surface": surface,
        "status": status,
        "summary": summary,
        "report_dir": str(report_dir),
        "primary": str(primary_path) if primary_path else "",
        "files": files,
    }

    if primary_path and primary_path.suffix.lower() == ".json":
        try:
            payload["primary_json"] = json.loads(read_text(primary_path))
        except json.JSONDecodeError as exc:
            payload["primary_json_error"] = str(exc)
        latest_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        md = [
            f"# AgentReady {surface} Report",
            "",
            f"- Generated: {generated}",
            f"- Repo: `{repo}`",
            f"- Status: `{status}`",
            f"- Primary: `{primary_path}`",
            f"- Summary: {summary or 'See primary artifact.'}",
            "",
            "## Artifacts",
            "",
        ]
        md.extend(f"- `{name}`" for name in files)
        latest_md.write_text("\n".join(md) + "\n", encoding="utf-8")
        return latest_md

    latest_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md = [
        f"# AgentReady {surface} Report",
        "",
        f"- Generated: {generated}",
        f"- Repo: `{repo}`",
        f"- Status: `{status}`",
        f"- Primary: `{primary_path or ''}`",
        f"- Summary: {summary or 'See primary artifact.'}",
        "",
        "## Artifacts",
        "",
    ]
    md.extend(f"- `{name}`" for name in files)
    if primary_path:
        md.extend(["", "## Primary Content", ""])
        if primary_path.suffix.lower() in {".md", ".markdown"}:
            md.append(read_text(primary_path))
        else:
            md.extend(["```text", read_text(primary_path)[-12000:], "```"])
    latest_md.write_text("\n".join(md) + "\n", encoding="utf-8")
    return latest_md


def infer_primary(report_dir: Path, surface: str) -> Path | None:
    patterns = SURFACE_PRIMARY_PATTERNS.get(surface, ["*.md", "*.json", "*.txt", "*.log"])
    for pattern in patterns:
        candidates = [
            path
            for path in report_dir.glob(pattern)
            if path.is_file() and path.name not in {"latest.md", "latest.json"}
        ]
        if candidates:
            return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)[0]
    files = [path for path in report_dir.iterdir() if path.is_file() and path.name not in {"latest.md", "latest.json"}]
    if not files:
        return None
    return sorted(files, key=lambda path: path.stat().st_mtime, reverse=True)[0]


def infer_status(surface: str, primary: Path | None) -> str:
    if primary is None:
        return "missing"
    if surface == "ci":
        text = read_text(primary)[-12000:].lower()
        if "fail " in text or "exit " in text and " = 0" not in text:
            return "fail"
        if "warn no known ci/test entrypoints detected" in text:
            return "warn"
    return "ok"


def repair_report_contracts(repo: Path, surfaces: list[str] | None = None) -> list[dict[str, str]]:
    selected = surfaces or ["repo-map", "gap-report", "architecture", "ci", "python-quality", "release-scorecard"]
    results: list[dict[str, str]] = []
    for surface in selected:
        report_dir = repo / ".agent-reports" / surface
        if not report_dir.exists():
            results.append(
                {
                    "surface": surface,
                    "status": "missing",
                    "report_dir": str(report_dir),
                    "latest": "",
                    "primary": "",
                    "summary": "Report directory is missing.",
                }
            )
            continue
        latest_md = report_dir / "latest.md"
        latest_json = report_dir / "latest.json"
        if latest_md.exists() and latest_json.exists():
            results.append(
                {
                    "surface": surface,
                    "status": "preserved",
                    "report_dir": str(report_dir),
                    "latest": str(latest_md),
                    "primary": str(latest_json),
                    "summary": "Existing latest.md/latest.json contract preserved.",
                }
            )
            continue
        primary = infer_primary(report_dir, surface)
        status = infer_status(surface, primary)
        summary = (
            "Canonical latest.md/latest.json pointers repaired from existing report artifacts."
            if primary
            else "Report directory exists but has no repairable artifacts."
        )
        latest = normalize_report(repo=repo, surface=surface, report_dir=report_dir, primary=primary, status=status, summary=summary)
        results.append(
            {
                "surface": surface,
                "status": status,
                "report_dir": str(report_dir),
                "latest": str(latest),
                "primary": str(primary) if primary else "",
                "summary": summary,
            }
        )
    return results


def write_repair_summary(repo: Path, results: list[dict[str, str]]) -> Path:
    report_dir = repo / ".agent-reports" / "report-contract"
    report_dir.mkdir(parents=True, exist_ok=True)
    generated = now_iso()
    payload = {
        "generated_at": generated,
        "repo": str(repo),
        "results": results,
        "missing": sum(1 for row in results if row["status"] == "missing"),
        "repaired": sum(1 for row in results if row["latest"]),
    }
    json_path = report_dir / "latest.json"
    md_path = report_dir / "latest.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        "# AgentReady Report Contract Repair",
        "",
        f"- Generated: {generated}",
        f"- Repo: `{repo}`",
        f"- Repaired: {payload['repaired']}",
        f"- Missing: {payload['missing']}",
        "",
        "| Surface | Status | Primary | Latest |",
        "| --- | --- | --- | --- |",
    ]
    for row in results:
        primary = row["primary"].replace("|", "\\|")
        latest = row["latest"].replace("|", "\\|")
        lines.append(f"| {row['surface']} | {row['status']} | `{primary}` | `{latest}` |")
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize AgentReady report latest.md/latest.json contracts.")
    parser.add_argument("action", nargs="?", default="normalize", choices=["normalize", "repair"])
    parser.add_argument("--repo", default=os.getcwd())
    parser.add_argument("--surface", default="")
    parser.add_argument("--surfaces", nargs="*", default=[])
    parser.add_argument("--report-dir", default="")
    parser.add_argument("--primary", default="")
    parser.add_argument("--status", default="ok")
    parser.add_argument("--summary", default="")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if args.action == "repair":
        results = repair_report_contracts(repo=repo, surfaces=args.surfaces or None)
        summary = write_repair_summary(repo, results)
        print(json.dumps({"repo": str(repo), "results": results}, indent=2))
        print(f"AgentReady report contract repair: {summary}")
        missing = any(row["status"] == "missing" for row in results)
        return 1 if missing else 0

    if not args.surface or not args.report_dir:
        raise SystemExit("--surface and --report-dir are required for normalize.")
    primary = Path(args.primary) if args.primary else None
    latest = normalize_report(
        repo=repo,
        surface=args.surface,
        report_dir=Path(args.report_dir).resolve(),
        primary=primary.resolve() if primary else None,
        status=args.status,
        summary=args.summary,
    )
    print(f"AgentReady report contract: {latest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
