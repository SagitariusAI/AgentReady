"""Source-signal / diff-test / tool-trajectory capture anatomy for the Agent Data Foundry.

Phase D1 of the module split (docs/refactors/AGENT_DATA_FOUNDRY_MODULE_SPLIT_PLAN.md):
the pure source-signal capture / git-status / diff-test anatomy helpers moved verbatim
out of agent_data_foundry.py with **no behavior change**. Pure leaf — depends only on
the stdlib (`re`) and `typing`.

These builders derive the honest "bones" of a receipt/task: which paths were touched,
which were tests/protected, what git operations occurred, what the diff added/removed
(assertion / mock / skip counts), and how work moved through tools. The cardinal rule
is preserved exactly: derive only what the record actually carries, and emit
empty/null rather than fabricate precision (path-only file ops stay `unknown`;
assertion/mock deltas stay null when there is no diff text).

The Dojo builder (`build_inhouse_dojo`), the training exporter, the historical-chat
parser, and the safety scan all stay in agent_data_foundry.py / their own leaves and
consume these helpers via the re-exported names.
"""
from __future__ import annotations

import re
from typing import Any

from agent_data_foundry_lib.io_jsonl import as_dict, as_list


def _is_test_path(path: str) -> bool:
    low = path.replace("\\", "/").lower()
    name = low.rsplit("/", 1)[-1]
    return "/tests/" in low or low.startswith("tests/") or name.startswith("test_") or name.endswith("_test.py") or "test" in name


def _is_protected_path(path: str) -> bool:
    low = path.replace("\\", "/").lower()
    markers = ("/tests/", "test_", "_test.", "doctrine", "constitution", "agent_workstate", "commit-guard", "release-scorecard", "pyproject", "requirements", ".gitignore", "stage.json")
    return any(marker in low for marker in markers)


def _is_test_command(command: str) -> bool:
    low = command.lower()
    return any(token in low for token in ("pytest", "tox", "nox", "unittest", " test", "test "))


def _norm_repo_path(path: str, repo: str | None = None) -> str:
    """Normalize a path to repo-relative POSIX when it lives under the record's
    own repo, so the captured envelope does not embed the absolute internal repo
    prefix. Paths outside the repo are POSIX-normalized but otherwise untouched;
    a later redaction pass (not this slice) is the gate before any export."""
    posix = str(path).replace("\\", "/").strip()
    if repo:
        repo_posix = str(repo).replace("\\", "/").rstrip("/")
        if repo_posix and posix.lower().startswith(repo_posix.lower() + "/"):
            return posix[len(repo_posix) + 1:]
    return posix


def _collect_source_paths(record: dict[str, Any], repo: str | None) -> list[str]:
    """Union of touched/changed paths a receipt or coordination task carries:
    declared diff paths, claimed lane paths, and evidence file paths."""
    raw: list[str] = []
    for key in ("paths_touched", "changed_files", "paths"):
        value = record.get(key)
        if isinstance(value, list):
            raw.extend(str(item) for item in value)
    for item in record.get("evidence") or []:
        if isinstance(item, dict) and item.get("path"):
            raw.append(str(item.get("path")))
        elif isinstance(item, str):
            raw.append(item)
    seen: list[str] = []
    for path in (_norm_repo_path(p, repo) for p in raw if str(p).strip()):
        if path not in seen:
            seen.append(path)
    return seen


def _collect_source_commands(record: dict[str, Any]) -> list[str]:
    commands: list[str] = []
    for key in ("commands_run", "commands"):
        value = record.get(key)
        if isinstance(value, list):
            commands.extend(str(item).strip() for item in value if str(item).strip())
    return commands


def _command_surface(command: str) -> str:
    """The leading tool/verb token of a command, for coarse surface grouping."""
    return command.strip().split()[0] if command.strip() else ""


def harvest_source_signals(record: dict[str, Any]) -> dict[str, Any]:
    """Minimal, honest source-signal envelope preserved at harvest time so the
    downstream diff_test_integrity capture has real input. Derives only from
    fields the receipt/task actually carries; emits empty lists / null rather
    than fabricating. Per-command exit codes are NOT present in receipts, so
    command_exit_codes is emitted empty (quality is a separate signal) — this
    block never invents precision it cannot observe."""
    repo: str | None = None
    for repo_key in ("repo", "repo_root"):
        value = record.get(repo_key)
        if isinstance(value, str) and value.strip():
            repo = value
            break
    paths = _collect_source_paths(record, repo)
    commands = _collect_source_commands(record)
    test_commands = [c for c in commands if _is_test_command(c)]
    # Real git operation status, if the receipt/task carried any. Normalized to
    # {op, path} with repo-relative paths; empty list when no status is present
    # (the diff/test capture then falls back to all-`unknown`, never guessed).
    file_status_raw = None
    for status_key in ("file_status", "git_status", "git_name_status", "name_status", "changed_file_status"):
        if record.get(status_key):
            file_status_raw = record.get(status_key)
            break
    file_status = [
        {"op": entry["op"], "path": _norm_repo_path(entry["path"], repo)}
        for entry in normalize_git_file_status(file_status_raw)
    ]
    # Raw diff text, if the receipt carried any. Stored at the source/evidence
    # layer; the redaction filter scans it and the Dojo keeps only derived counts
    # (never the raw patch). Null when absent -- the v0.3 parser then emits null.
    diff_patch = None
    for diff_key in DIFF_TEXT_FIELDS:
        value = record.get(diff_key)
        if isinstance(value, str) and value.strip():
            diff_patch = value
            break
        if isinstance(value, list) and value:
            joined = "\n".join(str(item) for item in value)
            if joined.strip():
                diff_patch = joined
                break
    selected_tools = [str(t) for t in as_list(record.get("selected_tools"))]
    available_tools = [str(t) for t in as_list(record.get("available_tools"))]
    return {
        "schema_version": "sf.source_signals.v0.4",
        "paths_touched": paths,
        "changed_file_count": len(paths),
        "commands_run": commands,
        "command_surfaces": sorted({s for s in (_command_surface(c) for c in commands) if s}),
        "command_exit_codes": [],
        "test_commands": test_commands,
        "test_command_present": bool(test_commands),
        "test_files_touched": sorted({p for p in paths if _is_test_path(p)}),
        "protected_path_touches": sorted({p for p in paths if _is_protected_path(p)}),
        "file_status": file_status,
        "diff_patch": diff_patch,
        "selected_tools": selected_tools,
        "available_tools": available_tools,
    }


def build_diff_test_integrity(record: dict[str, Any]) -> dict[str, Any]:
    """Capture the BONES of diff/test integrity from a record's available fields.
    Prefers a harvest-time `source_signals` envelope when present, falling back
    to the record's own top-level fields. Derives only what is honestly
    derivable; emits null/empty (never faked precision) for fields that require
    real diff parsing."""
    signals = as_dict(record.get("source_signals"))
    paths: list[str] = []
    if isinstance(signals.get("paths_touched"), list):
        paths.extend(str(item) for item in signals["paths_touched"])
    else:
        for key in ("paths_touched", "changed_files"):
            value = record.get(key)
            if isinstance(value, list):
                paths.extend(str(item) for item in value)
    if isinstance(signals.get("commands_run"), list):
        commands = [str(item) for item in signals["commands_run"]]
    else:
        commands = []
        for key in ("commands_run", "commands"):
            value = record.get(key)
            if isinstance(value, list):
                commands.extend(str(item) for item in value)
    test_files_changed = sorted({p for p in paths if _is_test_path(p)})
    protected_path_touches = sorted({p for p in paths if _is_protected_path(p)})
    test_commands = [c for c in commands if _is_test_command(c)]
    test_command = test_commands[0] if test_commands else None
    quality = as_dict(record.get("quality"))
    test_exit_code = None
    if test_command and isinstance(quality.get("passed"), bool):
        test_exit_code = 0 if quality.get("passed") else 1
    file_status = signals.get("file_status") if signals.get("file_status") is not None else record.get("file_status")
    real_ops = derive_file_op_types(file_status)
    file_op_types = real_ops if real_ops is not None else build_file_op_types(paths)
    diff_text = extract_diff_text(record)
    return {
        "schema_version": "sf.diff_test_integrity.v0.3",
        "diff_stat": {"files_changed": len(paths)} if paths else {},
        "file_op_types": file_op_types,
        "protected_path_touches": protected_path_touches,
        "test_files_changed": test_files_changed,
        "test_command": test_command,
        "test_exit_code": test_exit_code,
        "test_signal": {
            "test_files_touched_count": len(test_files_changed),
            "test_command_present": bool(test_commands),
            "test_command_count": len(test_commands),
        },
        "protected_signal": {
            "protected_path_touch_count": len(protected_path_touches),
        },
        "assertion_delta": derive_assertion_delta(diff_text),
        "mock_skip_signals": derive_mock_skip_signals(diff_text),
    }


def build_file_op_types(paths: list[str]) -> dict[str, int]:
    """Coarse file-operation counts. The current harvest sources (paths_touched /
    evidence paths) carry no create/modify/delete/rename distinction, so every
    touched path is counted as `unknown` rather than guessed — no fiction. Real
    op-type discrimination is a later slice that needs git-diff status, not a
    bare path list. The all-`unknown` shape keeps the schema forward-looking
    without overstating what was observed."""
    return {"created": 0, "modified": 0, "deleted": 0, "renamed": 0, "unknown": len(paths)}


# git status letter -> file operation. Copies and untracked produce a new file
# (created); type-change / unmerged are content changes (modified). Anything
# unrecognized stays `unknown` -- never guessed.
_GIT_STATUS_OP = {
    "A": "created", "M": "modified", "D": "deleted", "R": "renamed",
    "C": "created", "T": "modified", "U": "modified", "?": "created",
}


def _git_status_op(code: str) -> str:
    letter = str(code or "").strip()[:1].upper()
    return _GIT_STATUS_OP.get(letter, "unknown")


def _parse_git_status_line(line: str) -> dict[str, str] | None:
    """Parse one line of `git status --porcelain` or `git diff --name-status`.
    Returns {op, path} or None. For renames/copies the destination path wins."""
    raw = str(line).rstrip("\n")
    if not raw.strip():
        return None
    if "\t" in raw:
        # name-status: "A\tpath" or "R100\told\tnew"
        parts = [part for part in raw.split("\t") if part != ""]
        if len(parts) < 2:
            return None
        op = _git_status_op(parts[0])
        path = parts[-1].strip()
        return {"op": op, "path": path} if path else None
    # porcelain: two status columns (XY) then the path
    if len(raw) >= 3 and raw[2] == " ":
        xy, rest = raw[:2], raw[3:].strip()
    else:
        bits = raw.split(None, 1)
        if len(bits) != 2:
            return None
        xy, rest = bits[0], bits[1].strip()
    x = xy[0] if len(xy) > 0 else " "
    y = xy[1] if len(xy) > 1 else " "
    if xy.strip() == "??":
        op = "created"
    elif x not in (" ", "?"):
        op = _git_status_op(x)
    elif y != " ":
        op = _git_status_op(y)
    else:
        op = "unknown"
    if " -> " in rest:  # porcelain rename "old -> new"
        rest = rest.split(" -> ", 1)[1].strip()
    return {"op": op, "path": rest} if rest else None


def normalize_git_file_status(raw: Any) -> list[dict[str, str]]:
    """Normalize git status data into a list of {op, path}. Accepts a porcelain /
    name-status string blob, a list of such lines, or a list of structured
    {status|op, path|file|new_path} dicts. Unrecognized status -> `unknown`."""
    if raw is None:
        return []
    if isinstance(raw, str):
        items: list[Any] = raw.splitlines()
    elif isinstance(raw, (list, tuple)):
        items = list(raw)
    else:
        return []
    entries: list[dict[str, str]] = []
    for item in items:
        if isinstance(item, dict):
            code = item.get("op") or item.get("status") or item.get("change_type")
            path = item.get("path") or item.get("new_path") or item.get("file")
            if not path:
                continue
            op = code if code in ("created", "modified", "deleted", "renamed", "unknown") else _git_status_op(str(code))
            entries.append({"op": op, "path": str(path)})
        elif isinstance(item, str):
            parsed = _parse_git_status_line(item)
            if parsed:
                entries.append(parsed)
    return entries


def derive_file_op_types(raw: Any) -> dict[str, int] | None:
    """Real file-operation counts from git status data. Returns None when no
    usable status data is present, so the caller falls back to all-`unknown`
    rather than inventing operation types from a bare path list."""
    entries = normalize_git_file_status(raw)
    if not entries:
        return None
    counts = {"created": 0, "modified": 0, "deleted": 0, "renamed": 0, "unknown": 0}
    for entry in entries:
        op = entry["op"] if entry["op"] in counts else "unknown"
        counts[op] += 1
    return counts


# Fields a record / source_signals envelope may carry unified diff text under.
DIFF_TEXT_FIELDS = ("diff_patch", "diff_text", "patch", "unified_diff", "git_diff")

# Lightweight, language-reasonable line markers. Not AST -- a hint, not a parser.
_ASSERT_RE = re.compile(r"\bassert|\bexpect\s*\(|\.should\b|\bEXPECT_")
_MOCK_RE = re.compile(r"(?i)\b(?:mock|magicmock|monkeypatch|mocker)\b|@patch\b|\bpatch\s*\(")
_SKIP_RE = re.compile(r"(?i)pytest\.skip|mark\.skip|\bskipif\b|\bskiptest\b|unittest\.skip|@skip\b")
_XFAIL_RE = re.compile(r"(?i)\bxfail\b|mark\.xfail")


def extract_diff_text(source: Any) -> str | None:
    """Return unified diff text from a record or its source_signals envelope, if
    any field carries it. Accepts a string blob or a list of lines. None when no
    diff text is present -- the caller then leaves assertion/mock counts null."""
    if not isinstance(source, dict):
        return None
    signals = as_dict(source.get("source_signals"))
    for container in (signals, source):
        for key in DIFF_TEXT_FIELDS:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value
            if isinstance(value, list) and value:
                joined = "\n".join(str(item) for item in value)
                if joined.strip():
                    return joined
    return None


def _iter_diff_changes(diff_text: str):
    """Yield (sign, content) for added/removed diff lines, skipping the
    +++ / --- / @@ metadata lines so they never count as code changes."""
    for line in diff_text.splitlines():
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith("+"):
            yield "+", line[1:]
        elif line.startswith("-"):
            yield "-", line[1:]


def derive_assertion_delta(diff_text: str | None) -> dict[str, int | None]:
    """Count added/removed assert-like lines from diff text. Null when no diff
    text exists -- never fabricated, never inferred from filenames."""
    if not diff_text:
        return {"assertions_added": None, "assertions_removed": None}
    added = removed = 0
    for sign, content in _iter_diff_changes(diff_text):
        if _ASSERT_RE.search(content):
            if sign == "+":
                added += 1
            else:
                removed += 1
    return {"assertions_added": added, "assertions_removed": removed}


def derive_mock_skip_signals(diff_text: str | None) -> dict[str, int | None]:
    """Count added mock / skip / xfail lines from diff text. Null when no diff
    text exists. skips_added counts the skip-or-xfail family (per spec); xfail is
    also tracked on its own in xfail_added."""
    if not diff_text:
        return {"mocks_added": None, "skips_added": None, "xfail_added": None}
    mocks = skips = xfails = 0
    for sign, content in _iter_diff_changes(diff_text):
        if sign != "+":
            continue
        if _MOCK_RE.search(content):
            mocks += 1
        is_xfail = bool(_XFAIL_RE.search(content))
        if _SKIP_RE.search(content) or is_xfail:
            skips += 1
        if is_xfail:
            xfails += 1
    return {"mocks_added": mocks, "skips_added": skips, "xfail_added": xfails}


def strip_diff_text_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Remove raw diff text from a Dojo training row. The diff is evidence at the
    source layer (source_signals) and feeds the parsers, but only the DERIVED
    counts (assertion_delta / mock_skip_signals) belong in the lean training row.
    Strips top-level diff fields and source_signals.diff_patch."""
    cleaned = {key: value for key, value in row.items() if key not in DIFF_TEXT_FIELDS}
    signals = cleaned.get("source_signals")
    if isinstance(signals, dict) and any(key in signals for key in DIFF_TEXT_FIELDS):
        cleaned["source_signals"] = {key: value for key, value in signals.items() if key not in DIFF_TEXT_FIELDS}
    return cleaned


_FAILED_EVIDENCE_STATUSES = ("fail", "failed", "error", "red", "blocked")


def build_tool_call_trajectory(record: dict[str, Any]) -> dict[str, Any]:
    """Capture the BONES of how work moved through tools, from existing fields
    only. Available/selected tools are taken verbatim when present (never
    fabricated); otherwise a crude tool_sequence is mapped from commands_run and
    honestly labelled `command_receipt`. A command sequence is NOT model
    tool-call reasoning -- the trajectory_source says where it came from."""
    signals = as_dict(record.get("source_signals"))
    commands: list[str] = []
    for source in (signals, record):
        for key in ("commands_run", "commands"):
            value = source.get(key)
            if isinstance(value, list) and value:
                commands = [str(item) for item in value]
                break
        if commands:
            break
    available_raw = signals.get("available_tools") if isinstance(signals.get("available_tools"), list) and signals.get("available_tools") else record.get("available_tools")
    selected_raw = signals.get("selected_tools") if isinstance(signals.get("selected_tools"), list) and signals.get("selected_tools") else record.get("selected_tools")
    available_tools = [str(t) for t in available_raw] if isinstance(available_raw, list) else []
    selected_tools = [str(t) for t in selected_raw] if isinstance(selected_raw, list) else []

    if selected_tools:
        tool_sequence = list(selected_tools)
    elif commands:
        tool_sequence = [_command_surface(c) for c in commands if _command_surface(c)]
    else:
        tool_sequence = []

    tool_inputs_present = any(len(c.split()) > 1 for c in commands)
    evidence = as_list(record.get("evidence"))
    quality = as_dict(record.get("quality"))
    checks = as_list(quality.get("checks"))
    tool_outputs_present = bool(evidence) or bool(checks)

    failed_tools: list[str] = []
    for check in checks:
        if isinstance(check, dict) and check.get("ok") is False:
            failed_tools.append(str(check.get("name") or "check"))
    for row in evidence:
        if isinstance(row, dict) and str(row.get("status") or "").lower() in _FAILED_EVIDENCE_STATUSES:
            failed_tools.append(str(row.get("path") or row.get("meaning") or "evidence"))

    skipped = [str(t) for t in as_list(record.get("skipped_relevant_tools"))]
    reason = record.get("reason_for_tool_choice")
    reason = str(reason) if reason else None

    if available_tools or selected_tools:
        trajectory_source = "tool_record"
    elif commands:
        trajectory_source = "command_receipt"
    else:
        trajectory_source = "missing"

    return {
        "schema_version": "sf.tool_call_trajectory.v0.1",
        "available_tools": available_tools,
        "selected_tools": selected_tools,
        "tool_sequence": tool_sequence,
        "tool_inputs_present": tool_inputs_present,
        "tool_outputs_present": tool_outputs_present,
        "failed_tools": sorted(set(failed_tools)),
        "skipped_relevant_tools": skipped,
        "reason_for_tool_choice": reason,
        "trajectory_source": trajectory_source,
    }
