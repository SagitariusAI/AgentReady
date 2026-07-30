"""Coordination quality gates — port of `Get-AgentTextLength` (L441), `Test-AgentTaskStartQuality`
(L446-467), `Test-AgentClaimQuality` (L469-476), `Test-AgentHandoffQuality` (L478-501), and
`Write-AgentQualityFailure` (L503-514). These are governance thresholds, not cosmetics — preserved exactly."""
from __future__ import annotations

from agent_coordination.paths import protected_path_intent, to_path_list


def text_length(text) -> int:
    return len(str(text or "").strip())


def task_start_quality(title: str, summary: str = "", paths=None) -> list[str]:
    """Issues blocking a task-start (PS L446-467). Empty list = pass."""
    issues: list[str] = []
    if text_length(title) < 12:
        issues.append("Title must clearly identify the work, not just a ticket id.")
    if text_length(summary) < 20:
        issues.append("Summary must state intent/current scope in at least 20 characters.")
    normalized = to_path_list(paths)
    if not normalized:
        issues.append("Paths must include at least one repo path or directory claim.")
    issues.extend(protected_path_intent(normalized, title=title, summary=summary))
    return issues


def claim_quality(paths=None) -> list[str]:
    """Issues blocking a claim (PS L469-476)."""
    if not to_path_list(paths):
        return ["Claim must include at least one path; empty claims cannot protect concurrent work."]
    return []


def handoff_quality(task: dict, summary: str = "", evidence: str = "", next_action: str = "") -> list[str]:
    """Issues blocking a handoff (PS L478-501)."""
    issues: list[str] = []
    effective_summary = summary if summary else str(task.get("summary") or "")
    if text_length(effective_summary) < 20:
        issues.append("Handoff summary must state what changed/current state in at least 20 characters.")
    if not to_path_list(task.get("paths")):
        issues.append("Handoff task has no claimed paths; another agent cannot safely continue or avoid conflicts.")
    if text_length(evidence) < 20:
        issues.append("Handoff must include interpreted tests/evidence, not only report pointers.")
    if text_length(next_action) < 8:
        issues.append("Handoff must include the next safe action or state that no next action remains.")
    return issues


def quality_failure_message(kind: str, issues, override: str = "-AllowWeak") -> str:
    """The human-readable failure block (PS Write-AgentQualityFailure L503-514)."""
    lines = [f"{kind} quality gate failed:"]
    lines += [f"- {issue}" for issue in (issues or [])]
    lines.append(f"Use {override} only for an explicitly weak/emergency record, and explain the "
                 f"weakness in the summary/evidence.")
    return "\n".join(lines)
