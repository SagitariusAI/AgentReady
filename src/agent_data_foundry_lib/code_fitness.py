# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Code Fitness Runner for the Agent Data Foundry."""
from __future__ import annotations

import ast
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from agent_data_foundry_lib.io_jsonl import now_utc, read_json, rel, write_json
from agent_data_foundry_lib.paths import AGENTREADY_HOME

CODE_FITNESS_SCHEMA = "sf.code_fitness.v0.1"
_CF_HEAVY_IMPORTS = ("torch", "tensorflow", "transformers", "sklearn", "pandas", "numpy", "scipy")
_CF_SKIP_DIRS = {".venv", "node_modules", ".git", "data", ".agent-reports", "coordination", "worktrees", "__pycache__"}


def _cf_finding(severity: str, category: str, message: str, *, file: str | None = None, line: int | None = None,
                family: str = "", sign: str = "-", anchor: str = "WORKFLOW", repair_target: str | None = None) -> dict[str, Any]:
    return {"severity": severity, "category": category, "message": message, "file": file, "line": line,
            "curriculum_family": family, "sign": sign, "anchor": anchor, "repair_target": repair_target}


def _cf_python_files(root: Path, paths: list[str] | None) -> list[Path]:
    root = Path(root)
    if paths:
        return [Path(p) if Path(p).is_absolute() else root / p for p in paths]
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "*.py"],
                             capture_output=True, text=True, timeout=20, check=False)
        if out.returncode == 0 and out.stdout.strip():
            return [root / ln for ln in out.stdout.strip().splitlines() if ln.strip()]
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return sorted(p for p in root.rglob("*.py") if not any(part in _CF_SKIP_DIRS for part in p.parts))


def _cf_read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _cf_git_gate_state(root: Path) -> dict[str, Any]:
    """Read git + gate-marker state without mutating anything. Gate marker is read
    directly (independent of git) so it works in a fixture."""
    state: dict[str, Any] = {"git_available": False, "dirty_tree": None, "head": None,
                             "gate_status": None, "gate_ref": None, "gate_matches_head": None}
    try:
        head = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, check=False)
        if head.returncode == 0 and head.stdout.strip():
            state["git_available"] = True
            state["head"] = head.stdout.strip()
            status = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, timeout=15, check=False)
            state["dirty_tree"] = bool(status.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    marker = read_json(Path(root) / ".agentready" / "gate_status.json")
    if isinstance(marker, dict):
        state["gate_status"] = marker.get("status")
        state["gate_ref"] = marker.get("ref")
        if state["head"]:
            state["gate_matches_head"] = (marker.get("ref") == state["head"])
    return state


def _cf_structure(root: Path, files: list[Path]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    sizes: list[dict[str, Any]] = []
    for f in files:
        text = _cf_read(f)
        if text is None:
            continue
        nlines = text.count("\n") + 1
        relf = rel(root, f)
        sizes.append({"file": relf, "lines": nlines})
        if nlines > 900:
            findings.append(_cf_finding("BLOCK", "structure", f"{relf}: {nlines} lines (>900) -- god-file candidate; split by responsibility or get a owner-approved exemption",
                                        file=relf, family="module_structure", sign="-", anchor="WORKFLOW", repair_target="split by responsibility"))
        elif nlines > 600:
            findings.append(_cf_finding("WARN", "structure", f"{relf}: {nlines} lines (>600) -- responsibility review",
                                        file=relf, family="module_structure", sign="-", anchor="WORKFLOW", repair_target="review responsibility / plan a split"))
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.end_lineno is not None:
                span = node.end_lineno - node.lineno + 1
                if span > 150:
                    findings.append(_cf_finding("WARN", "structure", f"{relf}:{node.lineno} function {node.name}() is {span} lines (>150) -- split or write a justification",
                                                file=relf, line=node.lineno, family="function_size", sign="-", anchor="WORKFLOW", repair_target="split or write justification"))
                elif span > 80:
                    findings.append(_cf_finding("INFO", "structure", f"{relf}:{node.lineno} function {node.name}() is {span} lines (>80) -- review",
                                                file=relf, line=node.lineno, family="function_size", sign="-", anchor="WORKFLOW", repair_target="review length"))
        if nlines > 600 and "argparse" in text and re.search(r"def main\(", text):
            findings.append(_cf_finding("INFO", "structure", f"{relf}: CLI-heavy central module ({nlines} lines) -- keep CLI dispatch thin; move logic into serviceable modules",
                                        file=relf, family="module_structure", sign="-", anchor="WORKFLOW", repair_target="thin CLI dispatch + split logic"))
    sizes.sort(key=lambda x: -x["lines"])
    return findings, sizes[:25]


def _cf_comments(root: Path, files: list[Path]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for f in files:
        if f.name.startswith("test_"):
            continue  # do not require docstrings on every test function
        text = _cf_read(f)
        if text is None:
            continue
        relf = rel(root, f)
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                        and not node.name.startswith("_") and node.name not in ("main",) \
                        and not node.name.startswith("test_") and ast.get_docstring(node) is None:
                    findings.append(_cf_finding("INFO", "comments", f"{relf}:{node.lineno} public {type(node).__name__} {node.name} has no docstring",
                                                file=relf, line=node.lineno, family="documentation", sign="-", anchor="PROVENANCE", repair_target="add a why-focused docstring"))
        for i, line in enumerate(text.split("\n"), start=1):
            todo = re.search(r"#.*\b(TODO|FIXME)\b(.*)$", line)
            if todo and not re.search(r"[(@]|:\s*\S", todo.group(2)):
                findings.append(_cf_finding("WARN", "comments", f"{relf}:{i} {todo.group(1)} without owner/context",
                                            file=relf, line=i, family="documentation", sign="-", anchor="PROVENANCE", repair_target="add owner/context or remove"))
            if re.search(r"#\s*(XXX|HACK|OBSOLETE|DEPRECATED)\b", line, re.I):
                findings.append(_cf_finding("INFO", "comments", f"{relf}:{i} suspicious obsolete/hack marker -- verify or remove",
                                            file=relf, line=i, family="documentation", sign="-", anchor="PROVENANCE", repair_target="verify or remove stale comment"))
    return findings


def _cf_serviceability(root: Path, files: list[Path]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    destructive = (r"shutil\.rmtree", r"os\.remove\(", r"os\.unlink\(", r"\.unlink\(", r"rm\s+-rf")
    for f in files:
        text = _cf_read(f)
        if text is None:
            continue
        relf = rel(root, f)
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, ast.ExceptHandler):
                    broad = node.type is None or (isinstance(node.type, ast.Name) and node.type.id in ("Exception", "BaseException"))
                    swallowed = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
                    if broad and swallowed:
                        findings.append(_cf_finding("WARN", "serviceability", f"{relf}:{node.lineno} broad except + pass -- swallowed failure",
                                                    file=relf, line=node.lineno, family="error_handling", sign="-", anchor="RIGHTS", repair_target="catch the specific exception / surface an actionable error"))
        for i, line in enumerate(text.split("\n"), start=1):
            if any(re.search(pat, line) for pat in destructive):
                findings.append(_cf_finding("WARN", "serviceability", f"{relf}:{i} destructive operation -- ensure it is guarded/confirmed and side-effects isolated",
                                            file=relf, line=i, family="serviceability", sign="-", anchor="RIGHTS", repair_target="guard/confirm destructive op; isolate side effect"))
            if re.search(r"""['"](?:[A-Za-z]:\\\\|/(?:home|usr|etc|var|root)/)""", line):
                findings.append(_cf_finding("INFO", "serviceability", f"{relf}:{i} hardcoded absolute path -- prefer an explicit/configurable path",
                                            file=relf, line=i, family="serviceability", sign="-", anchor="RIGHTS", repair_target="make the path explicit/configurable"))
    return findings


def _cf_hardware(root: Path, files: list[Path]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    read_calls = (".read_text(", "read_json(", "read_jsonl(")
    for f in files:
        text = _cf_read(f)
        if text is None:
            continue
        relf = rel(root, f)
        lines = text.split("\n")
        is_cli = "argparse" in text or bool(re.search(r"def main\(", text))
        for i, line in enumerate(lines, start=1):
            mod = re.match(r"(?:from|import)\s+(\w+)", line)  # top-level (no indent)
            if mod and mod.group(1) in _CF_HEAVY_IMPORTS and not line[:1].isspace():
                findings.append(_cf_finding("WARN" if is_cli else "INFO", "hardware",
                                            f"{relf}:{i} top-level heavy import '{mod.group(1)}'" + (" on a CLI/report path" if is_cli else ""),
                                            file=relf, line=i, family="runtime_overhead", sign="-", anchor="ROUNDTRIP", repair_target="lazy-import on the path that needs it"))
        for i, line in enumerate(lines):
            if re.match(r"\s*(for|while)\b", line):
                indent = len(line) - len(line.lstrip())
                for j in range(i + 1, min(i + 30, len(lines))):
                    nxt = lines[j]
                    if not nxt.strip():
                        continue
                    if len(nxt) - len(nxt.lstrip()) <= indent:
                        break
                    if any(rc in nxt for rc in read_calls):
                        findings.append(_cf_finding("WARN", "hardware", f"{relf}:{j + 1} possible file read inside a loop -- hoist/cache to avoid repeated reads",
                                                    file=relf, line=j + 1, family="runtime_overhead", sign="-", anchor="ROUNDTRIP", repair_target="hoist the read out of the loop or cache it"))
                        break
        nlines = text.count("\n") + 1
        if nlines > 600 and "read_jsonl" in text and not re.search(r"sha256|hashlib|cache", text):
            findings.append(_cf_finding("INFO", "hardware", f"{relf}: large pipeline file with no hash/cache strategy",
                                        file=relf, family="runtime_overhead", sign="-", anchor="ROUNDTRIP", repair_target="add a hash/cache to skip unchanged work"))
    return findings


def _cf_tool_availability() -> dict[str, str]:
    return {tool: ("available" if shutil.which(tool) else "not_available")
            for tool in ("ruff", "gitleaks", "bandit", "pip-audit", "semgrep")}


def _cf_ruff_available() -> bool:
    if shutil.which("ruff"):
        return True
    import importlib.util
    return importlib.util.find_spec("ruff") is not None


def _cf_run_ruff(root: Path, files: list[Path]) -> bool | None:
    if not files or not _cf_ruff_available():
        return None
    try:
        out = subprocess.run([sys.executable, "-m", "ruff", "check", *[str(f) for f in files]],
                             capture_output=True, text=True, timeout=180, check=False, cwd=str(root))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return out.returncode == 0


def _cf_debug_gaps(root: Path, git_state: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Report missing test/debug evidence for CHANGED behavioral files. With no
    change context, report not_evaluated -- never a false pass, never fabricated."""
    if not git_state.get("git_available"):
        return {"status": "not_evaluated", "reason": "no git change context", "changed_files": [], "gaps": []}, []
    try:
        out = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, timeout=15, check=False)
    except (OSError, ValueError, subprocess.SubprocessError):
        return {"status": "not_evaluated", "reason": "git error", "changed_files": [], "gaps": []}, []
    changed = [ln[3:].strip() for ln in out.stdout.splitlines() if ln.strip().endswith(".py")]
    if not changed:
        return {"status": "not_evaluated", "reason": "no working-tree python changes", "changed_files": [], "gaps": []}, []
    behavioral = [c for c in changed if c.startswith("src/") and not Path(c).name.startswith("test_")]
    test_changes = [c for c in changed if "test" in c.lower()]
    gaps = [c for c in behavioral if not test_changes]
    findings = [_cf_finding("WARN", "debug", f"{g} changed without a related test change -- prove behavior (reproduce-first/focused test) or record an exemption",
                            file=g, family="test_evidence", sign="-", anchor="ROUNDTRIP", repair_target="add reproduce-first/focused test or record exemption")
                for g in gaps]
    return {"status": "evaluated", "changed_files": changed, "gaps": gaps}, findings


def _cf_block(findings: list[dict[str, Any]], lint_clean: bool | None,
              git_state: dict[str, Any]) -> dict[str, Any]:
    blocking = [f for f in findings if f["severity"] == "BLOCK"]
    warnings = [f for f in findings if f["severity"] == "WARN"]

    def has_warn(category: str) -> bool:
        return any(f["category"] == category and f["severity"] in ("BLOCK", "WARN") for f in findings)

    gate_ok = (git_state.get("gate_status") == "pass" and git_state.get("gate_matches_head")) if git_state.get("gate_status") else None
    no_structure_block = not any(f["category"] == "structure" and f["severity"] == "BLOCK" for f in findings)

    def brief(f: dict[str, Any]) -> dict[str, Any]:
        return {"category": f["category"], "message": f["message"], "file": f["file"],
                "line": f["line"], "curriculum_family": f["curriculum_family"], "sign": f["sign"], "repair_target": f["repair_target"]}

    return {
        "schema_version": CODE_FITNESS_SCHEMA,
        "lint_clean": lint_clean,
        "tests_passed": gate_ok,
        "debug_receipt_present": None,
        "structure_ok": no_structure_block,
        "comments_ok": not has_warn("comments"),
        "file_split_ok": no_structure_block,
        "security_scan_ok": None,
        "runtime_evidence_ok": None,
        "serviceability_ok": not has_warn("serviceability"),
        "hardware_overhead_reviewed": True,
        "score": "BLOCK" if blocking else ("WARN" if warnings else "PASS"),
        "blocking_findings": [brief(f) for f in blocking],
        "warnings": [brief(f) for f in warnings],
    }


def code_fitness_scan(root: Path | str = AGENTREADY_HOME, paths: list[str] | None = None,
                      output_path: str | Path | None = None, run_lint: bool | None = None) -> dict[str, Any]:
    """Deterministic, dry-run/report-only code-fitness scan. Emits the code_fitness
    block + per-category reports. Never mutates code, never auto-fixes, never writes
    40_release_ready. Unknown stays explicit; inherited debt is reported as state."""
    root = Path(root)
    out_dir = Path(output_path) if output_path else (root / "data" / "training-library" / "30_curated" / "internal" / "code-fitness")
    out_dir.mkdir(parents=True, exist_ok=True)
    files = [f for f in _cf_python_files(root, paths) if f.exists()]

    git_state = _cf_git_gate_state(root)
    structure_findings, sizes = _cf_structure(root, files)
    comment_findings = _cf_comments(root, files)
    serviceability_findings = _cf_serviceability(root, files)
    hardware_findings = _cf_hardware(root, files)
    tools = _cf_tool_availability()
    if run_lint is None:
        run_lint = _cf_ruff_available()
    lint_clean = _cf_run_ruff(root, files) if run_lint else None
    debug_report, debug_findings = _cf_debug_gaps(root, git_state)

    if git_state.get("dirty_tree"):
        debug_findings.append(_cf_finding("WARN", "git", "working tree is dirty -- DONE requires a clean tree",
                                          family="repo_hygiene", sign="-", anchor="ROUNDTRIP", repair_target="commit or set aside changes"))
    if git_state.get("gate_status") and git_state.get("gate_matches_head") is False:
        debug_findings.append(_cf_finding("WARN", "git", "gate marker ref != HEAD -- re-run the gate after the latest commit",
                                          family="repo_hygiene", sign="-", anchor="ROUNDTRIP", repair_target="re-run agent-ci-local"))

    all_findings = structure_findings + comment_findings + serviceability_findings + hardware_findings + debug_findings
    all_findings.sort(key=lambda f: (f["file"] or "", f["line"] or 0, f["category"], f["message"]))
    block = _cf_block(all_findings, lint_clean, git_state)

    severity_counts = {sev: sum(1 for f in all_findings if f["severity"] == sev) for sev in ("BLOCK", "WARN", "INFO")}
    write_json(out_dir / "code_fitness_report.json", {
        "schema_version": "sf.code_fitness_report.v0.1", "generated_at": now_utc(),
        "files_scanned": len(files), "git_gate_state": git_state, "code_fitness": block,
        "severity_counts": severity_counts, "findings": all_findings,
    })
    write_json(out_dir / "code_structure_report.json", {"generated_at": now_utc(), "largest_files": sizes,
               "findings": [f for f in structure_findings if f["severity"] != "INFO" or f["category"] == "structure"]})
    write_json(out_dir / "file_split_report.json", {"generated_at": now_utc(),
               "files_over_600": [s for s in sizes if s["lines"] > 600],
               "findings": [f for f in structure_findings if "lines" in f["message"] or "function" in f["message"]]})
    write_json(out_dir / "comment_docstring_report.json", {"generated_at": now_utc(), "findings": comment_findings})
    write_json(out_dir / "debug_receipt_gap_report.json", {"generated_at": now_utc(), **debug_report})
    write_json(out_dir / "optional_scanner_availability_report.json", {"generated_at": now_utc(),
               "tools": tools, "ruff_lint_clean": lint_clean,
               "note": "missing tools are 'not_available'; this is not a failure."})
    write_json(out_dir / "hardware_overhead_risk_report.json", {"generated_at": now_utc(), "findings": hardware_findings})

    return {
        "status": "SCANNED", "mode": "report_only", "no_mutation": True, "wrote_release_ready": False,
        "files_scanned": len(files), "score": block["score"], "severity_counts": severity_counts,
        "lint_clean": lint_clean, "tools": tools, "output_root": rel(root, out_dir),
    }
