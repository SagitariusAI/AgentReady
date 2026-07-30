# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Software Factory Capture Runtime v0.1 — local-first, deterministic work capture.

Records real work (commands, git state, logs, receipts) as it happens, with no dependency on
Claude/Codex/ChatGPT and no network. JSONL is the source of truth; SQLite is a query index;
stdout/stderr logs are stored redacted. Optional local-model summarization (v0.2) consumes
receipts, it never replaces them.

Public surface (import from `factory_capture`):
    resolve_store, Store            -- the per-repo capture store
    run_command                     -- run + capture a command as a receipt
    new_event, append_event         -- the event schema + append-only write
    capture_git_state               -- deterministic git snapshot
    redact_text                     -- local secret redaction
    install_hooks, uninstall_hooks  -- git capture hooks
    summarize                       -- deterministic summary
    main                            -- the CLI entry point

CLI: `python -m factory_capture <init|run|status|tail|hooks|note|summarize>`.
"""
from __future__ import annotations

from factory_capture.cli import main
from factory_capture.common import now_iso
from factory_capture.events import CAPTURE_EVENT_SCHEMA, EVENT_TYPES, append_event, new_event
from factory_capture.gitstate import capture_git_state
from factory_capture.governed import auto_capture_current_process
from factory_capture.hooks import install_hooks, uninstall_hooks
from factory_capture.redaction import redact_text
from factory_capture.runner import run_command
from factory_capture.store import Store, resolve_store
from factory_capture.summarize import summarize

__version__ = "0.1.0"

__all__ = [
    "Store", "resolve_store", "run_command", "new_event", "append_event",
    "capture_git_state", "auto_capture_current_process", "redact_text", "install_hooks", "uninstall_hooks",
    "summarize", "now_iso", "main", "CAPTURE_EVENT_SCHEMA", "EVENT_TYPES", "__version__",
]
