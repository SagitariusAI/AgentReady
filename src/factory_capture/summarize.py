"""Deterministic, LLM-free summary over captured events. Optional --ollama enrichment degrades
gracefully (and is off by default): if Ollama is not reachable, the deterministic summary still
stands. A model summarizer consumes receipts; it never replaces them."""
from __future__ import annotations

from collections import Counter

from factory_capture.events import all_events, append_event, new_event
from factory_capture.store import Store

_CHECK_TOKENS = ("pytest", "ruff", "mypy", "tox", "coverage", "test", "check", "lint", "bandit")


def summarize(store: Store, use_ollama: bool = False) -> dict:
    events = all_events(store)
    commands = [e for e in events if e.get("event_type") == "command_run"]
    failures = [e for e in commands if e.get("status") in ("failure", "error")]

    touched: Counter = Counter()
    for event in commands:
        for path in (event.get("git_after") or {}).get("changed_files", []):
            touched[path] += 1

    commits: list[str] = []
    for event in events:
        commit = (event.get("git_after") or {}).get("commit", "")
        if commit and commit not in commits:
            commits.append(commit)

    checks = [
        " ".join(e.get("command") or [])
        for e in commands
        if any(tok in " ".join(e.get("command") or []).lower() for tok in _CHECK_TOKENS)
    ]

    summary = {
        "event_count": len(events),
        "command_count": len(commands),
        "failure_count": len(failures),
        "most_touched_files": touched.most_common(10),
        "latest_commits": commits[-5:],
        "latest_check_commands": checks[-5:],
        "ollama": None,
    }
    if use_ollama:
        summary["ollama"] = _try_ollama(summary)
    return summary


def _try_ollama(summary: dict) -> dict:
    """Optional local-model enrichment. v0.1 stub: report unavailable rather than fabricate."""
    try:
        import urllib.request  # noqa: PLC0415 - imported lazily so the deterministic path needs nothing

        req = urllib.request.Request("http://127.0.0.1:11434/api/tags")  # noqa: S310  # nosemgrep: python.lang.security.audit.insecure-transport.urllib.insecure-request-object.insecure-request-object
        with urllib.request.urlopen(req, timeout=1) as resp:  # nosec B310
            reachable = resp.status == 200
    except Exception:  # noqa: BLE001 - any failure means "no local model"; deterministic summary stands
        reachable = False
    return {
        "available": reachable,
        "note": "ollama reachable; narrative summarization deferred to v0.2" if reachable
        else "ollama not reachable — deterministic summary only (expected for v0.1)",
    }


def render_summary(summary: dict) -> str:
    lines = [
        "# Factory Capture Summary",
        "",
        f"- Events: {summary['event_count']}",
        f"- Commands: {summary['command_count']}",
        f"- Failures: {summary['failure_count']}",
        "",
        "## Most touched files",
    ]
    lines += [f"- {path} ({count})" for path, count in summary["most_touched_files"]] or ["- (none)"]
    lines += ["", "## Latest commits"]
    lines += [f"- {c[:12]}" for c in summary["latest_commits"]] or ["- (none)"]
    lines += ["", "## Latest check commands"]
    lines += [f"- {c}" for c in summary["latest_check_commands"]] or ["- (none)"]
    if summary.get("ollama") is not None:
        lines += ["", f"## Ollama: {summary['ollama']['note']}"]
    return "\n".join(lines) + "\n"


def summarize_and_record(store: Store, use_ollama: bool = False) -> tuple[dict, dict]:
    """Compute the summary and append a `summary` capture event embedding it."""
    summary = summarize(store, use_ollama=use_ollama)
    event = new_event("summary", exit_code=0, status="success")
    event["summary"] = summary
    append_event(store, event)
    return summary, event
