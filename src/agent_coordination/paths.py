"""Path normalization + claim-overlap + protected-intent — the claim/guard matching brain.

Port of `bin/agent-coordination-lib.ps1`: `Normalize-AgentPath` (L175), `ConvertTo-AgentPathList`
(L181-202), `Test-AgentPathOverlap` (L258-264), `Get-AgentProtectedSurface` (L266-303),
`Test-AgentProtectedPathIntent` (L305-328), `Get-AgentPathConflicts` (L330-358).

CRITICAL invariant (PS L181-193): each `-Paths` element is split on commas FIRST, because a
non-PowerShell caller (bash/JSON/Python) routinely passes the single string "a,b,c". Without splitting,
that whole blob is stored as ONE path the commit-guard can never match — wrongly BLOCKING a legitimately
claimed commit. This is exactly why a Python caller already works through the guard today.

PowerShell `-match` is case-insensitive, so the protected-surface patterns use re.IGNORECASE.
"""
from __future__ import annotations

import re

from agent_coordination.tasks import get_tasks

# Protected surfaces (Get-AgentProtectedSurface L271-292) — verbatim patterns + intent terms.
_PROTECTED_SURFACES = (
    {
        "category": "doctrine",
        "pattern": re.compile(
            r"^(docs/(AGENT_CONSTITUTION|AGENT_.*DOCTRINE|AGENT_TOOL_SELECTION_DOCTRINE|"
            r"CODEX_CLAUDE_AGENT_PROMPT|MSI_AGENTIC_SOFTWARE_COMPANY_ONBOARDING|"
            r"PRODUCTION_MATURITY_DOCTRINE|SERVICE_EXPOSURE_POLICY)\.md)$", re.I),
        "terms": ("doctrine", "constitution", "governance", "policy", "factory rule", "factory-rule",
                  "rule enforcement"),
    },
    {
        "category": "gate",
        "pattern": re.compile(
            r"^(bin/(agent-(commit-guard|install-commit-guard|policy-gate|release-scorecard|"
            r"release-readiness|task-start|task-claim|task-handoff|task-review|tool-router|"
            r"vault-code-separation)\.ps1)|src/(agent_workstate|agent_policy_gate|"
            r"agent_release_readiness|agent_production_maturity|agent_vault_code_separation)\.py)$", re.I),
        "terms": ("gate", "guard", "scorecard", "release", "policy", "verifier", "workstate",
                  "enforcement", "governance"),
    },
    {
        "category": "test",
        "pattern": re.compile(r"^(tests|smoke)/", re.I),
        "terms": ("test", "tests", "regression", "verification", "verifier", "quality", "gate", "smoke"),
    },
    {
        "category": "manifest",
        "pattern": re.compile(
            r"(^|/)(pyproject\.toml|requirements.*\.txt|uv\.lock|poetry\.lock|package-lock\.json|"
            r"pnpm-lock\.yaml|yarn\.lock|Cargo\.toml|Cargo\.lock|osv-scanner\.toml|"
            r"renovate(\.json|\.json5)?|package\.json)$", re.I),
        "terms": ("dependency", "dependencies", "package", "packaging", "manifest", "lock",
                  "supply-chain", "security", "version"),
    },
)


def normalize_path(path: str) -> str:
    if not path:
        return ""
    return path.replace("\\", "/").strip().strip("/")


def to_path_list(paths) -> list[str]:
    """Split-on-comma-first, normalize, drop empties. Port of ConvertTo-AgentPathList (L181-202)."""
    if paths is None:
        return []
    if isinstance(paths, str):
        paths = [paths]
    out = []
    for item in paths:
        if item is None:
            continue
        for piece in str(item).split(","):
            norm = normalize_path(piece)
            if norm:
                out.append(norm)
    return out


def path_overlap(a: str, b: str) -> bool:
    """True if a==b or one is a parent dir of the other. Port of Test-AgentPathOverlap (L258-264)."""
    a_norm, b_norm = normalize_path(a), normalize_path(b)
    if not a_norm or not b_norm:
        return False
    return a_norm == b_norm or a_norm.startswith(f"{b_norm}/") or b_norm.startswith(f"{a_norm}/")


def protected_surface(path: str) -> dict | None:
    """The protected category for a path (or None). Port of Get-AgentProtectedSurface (L266-303)."""
    p = normalize_path(path)
    if not p:
        return None
    leaf = p.rsplit("/", 1)[-1]
    for surface in _PROTECTED_SURFACES:
        if surface["pattern"].search(p) or surface["pattern"].search(leaf):
            return {"category": surface["category"], "path": p, "terms": surface["terms"]}
    return None


def protected_path_intent(paths, title: str = "", summary: str = "") -> list[str]:
    """Issues where a protected path lacks matching intent. Port of Test-AgentProtectedPathIntent (L305-328)."""
    issues: list[str] = []
    intent = f"{title}\n{summary}".lower()
    for p in to_path_list(paths):
        surface = protected_surface(p)
        if surface is None:
            continue
        if not any(str(term).lower() in intent for term in surface["terms"]):
            issues.append(
                f"Protected path '{surface['path']}' ({surface['category']}) requires explicit "
                f"{surface['category']} intent in task title/summary. This prevents hidden doctrine, "
                f"gate, test, or manifest drift.")
    return issues


def path_conflicts(repo, paths, exclude_task_id: str = "") -> list[dict]:
    """Active-task claims overlapping the requested paths. Port of Get-AgentPathConflicts (L330-358)."""
    normalized = to_path_list(paths)
    if not normalized:
        return []
    conflicts: list[dict] = []
    for task in get_tasks(repo, status=("open", "claimed", "in_progress", "handoff", "review")):
        if exclude_task_id and task.get("id") == exclude_task_id:
            continue
        for existing in to_path_list(task.get("paths")):
            for candidate in normalized:
                if path_overlap(existing, candidate):
                    conflicts.append({
                        "task_id": task.get("id"), "status": task.get("status"),
                        "agent": task.get("agent"), "existing_path": existing,
                        "requested_path": candidate, "title": task.get("title"),
                    })
    return conflicts
