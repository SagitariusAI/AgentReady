# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""factory-capture command-line interface.

Subcommands: init, run, status, tail, hooks {install,uninstall,status}, note, summarize, hook.
Invoke as ``python -m factory_capture <cmd>`` (or via the bin/factory-capture wrapper).
The capture runtime requires no LLM and no network."""
from __future__ import annotations

import argparse
import json
import sys

from factory_capture.events import append_event, last_events, new_event
from factory_capture.fleet import deploy_fleet, fleet_status
from factory_capture.gitstate import capture_git_state, find_repo_root
from factory_capture.hooks import hooks_state, install_hooks, uninstall_hooks
from factory_capture.redaction import redact_text
from factory_capture.report import render_status, render_tail, status
from factory_capture.runner import run_command
from factory_capture.store import resolve_store
from factory_capture.summarize import render_summary, summarize_and_record


def _require_store():
    store = resolve_store()
    if not store.exists():
        sys.stderr.write("factory-capture: store not initialized — run `factory-capture init` first.\n")
        return None
    return store


def _cmd_run(raw: list[str]) -> int:
    if raw and raw[0] == "--":
        raw = raw[1:]
    if not raw:
        sys.stderr.write("usage: factory-capture run -- <command> [args...]\n")
        return 2
    store = _require_store()
    if store is None:
        return 1
    event = run_command(store, raw)
    code = event.get("exit_code")
    return int(code) if isinstance(code, int) else 0


def _cmd_init(args) -> int:
    store = resolve_store()
    result = store.init(force=args.force)
    if result["already_existed"] and not result["created"]:
        print(f"factory-capture: store already exists at {result['root']} (use --force to reinitialize)")
        return 1
    print(f"factory-capture: initialized store at {result['root']}")
    return 0


def _cmd_status(_args) -> int:
    store = _require_store()
    if store is None:
        return 1
    print(render_status(status(store)), end="")
    return 0


def _cmd_tail(args) -> int:
    store = _require_store()
    if store is None:
        return 1
    events = last_events(store, args.n)
    if args.json:
        for event in events:
            print(json.dumps(event, ensure_ascii=True))
    else:
        print(render_tail(events), end="")
    return 0


def _cmd_hooks(args) -> int:
    store = _require_store()
    if store is None:
        return 1
    repo_root = find_repo_root(store.root.parent)
    if args.action == "install":
        result = install_hooks(repo_root)
    elif args.action == "uninstall":
        result = uninstall_hooks(repo_root)
    else:
        result = hooks_state(repo_root)
    print(json.dumps(result, indent=2))
    return 0


def _cmd_note(args) -> int:
    store = _require_store()
    if store is None:
        return 1
    redacted, findings = redact_text(args.text)
    event = new_event("manual_note", status="success")
    event["text"] = redacted
    event["redaction"] = {"applied": bool(findings), "findings": findings}
    event["repo_root"] = str(find_repo_root(store.root.parent))
    append_event(store, event)
    print(f"factory-capture: note recorded ({event['event_id']})")
    return 0


def _cmd_summarize(args) -> int:
    store = _require_store()
    if store is None:
        return 1
    summary, _ = summarize_and_record(store, use_ollama=args.ollama)
    print(render_summary(summary), end="")
    return 0


def _cmd_hook(args) -> int:
    """Internal: invoked by an installed git hook. Records a git_hook event; never blocks git."""
    try:
        store = resolve_store()
        if not store.exists():
            return 0
        repo_root = find_repo_root(store.root.parent)
        event = new_event("git_hook", status="success")
        event["command"] = ["git-hook", args.name]
        event["repo_root"] = str(repo_root)
        event["git_after"] = capture_git_state(repo_root)
        append_event(store, event)
    except Exception:  # noqa: BLE001 - a hook must never break the owner's git operation
        return 0
    return 0


def _cmd_chat_inbox(args) -> int:
    from factory_capture import chat_inbox
    store = resolve_store()
    if args.action == "init":
        result = chat_inbox.init_inbox(store)
        print(f"factory-capture chat-inbox: initialized at {result['root']}")
        return 0
    if not chat_inbox.inbox_paths(store)["config"].exists():
        sys.stderr.write("factory-capture chat-inbox: not initialized -- run `factory-capture chat-inbox init` first.\n")
        return 1
    if args.action == "scan":
        result = chat_inbox.scan(store)
        if result.get("error"):
            sys.stderr.write(result["error"] + "\n")
            return 1
        print(f"chat-inbox scan: {result['scanned']} item(s)")
        for item in result["results"]:
            tail = f" (exit {item['exit_code']}, event {item['capture_event_id']})" if item.get("capture_event_id") else ""
            print(f"  {item['source']} -> {item['status']}{tail}")
    elif args.action == "status":
        print(chat_inbox.render_status(chat_inbox.status(store)), end="")
    elif args.action == "watch":
        sys.stderr.write(f"factory-capture chat-inbox: watching every {args.interval}s (Ctrl-C to stop)\n")
        chat_inbox.watch(store, interval=args.interval)
    return 0


def _cmd_fleet(args) -> int:
    result = (
        deploy_fleet(args.agentready_home)
        if args.action == "deploy"
        else fleet_status(args.agentready_home)
    )
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser("factory-capture", description="Local-first work capture runtime.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser("init", help="create the local capture store")
    init.add_argument("--force", action="store_true", help="reinitialize even if a store exists")
    init.set_defaults(func=_cmd_init)

    sub.add_parser("status", help="show store + repo + capture status").set_defaults(func=_cmd_status)

    tail = sub.add_parser("tail", help="print the last N events")
    tail.add_argument("-n", type=int, default=10)
    tail.add_argument("--json", action="store_true")
    tail.set_defaults(func=_cmd_tail)

    hooks = sub.add_parser("hooks", help="install/uninstall/status git capture hooks")
    hooks.add_argument("action", choices=["install", "uninstall", "status"])
    hooks.set_defaults(func=_cmd_hooks)

    note = sub.add_parser("note", help="record a manual note event")
    note.add_argument("text")
    note.set_defaults(func=_cmd_note)

    summ = sub.add_parser("summarize", help="deterministic summary of captured work")
    summ.add_argument("--ollama", action="store_true", help="optional local-model enrichment (off by default)")
    summ.set_defaults(func=_cmd_summarize)

    hook = sub.add_parser("hook", help="(internal) record a git_hook event from a git hook")
    hook.add_argument("name")
    hook.set_defaults(func=_cmd_hook)

    chat = sub.add_parser("chat-inbox", help="historical-chat folder-drop inbox (init/scan/watch/status)")
    chat.add_argument("action", choices=["init", "scan", "watch", "status"])
    chat.add_argument("--interval", type=int, default=10, help="watch poll interval seconds")
    chat.set_defaults(func=_cmd_chat_inbox)

    fleet = sub.add_parser("fleet", help="deploy or audit capture across the AgentReady project registry")
    fleet.add_argument("action", choices=["status", "deploy"])
    fleet.add_argument("--agentready-home", help="AgentReady root containing the managed-project registry")
    fleet.set_defaults(func=_cmd_fleet)
    return parser


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    # `run` takes a raw wrapped command after `--`; handle it before argparse so flags pass through.
    if argv and argv[0] == "run":
        return _cmd_run(argv[1:])
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
