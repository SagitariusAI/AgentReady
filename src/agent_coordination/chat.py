# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Provider-neutral, best-effort hooks for coordination messages.

Callers may inject a publisher or unread-message reader. The public default is
an offline no-op, so importing or using coordination cannot contact a network
service or depend on machine-specific configuration.
"""
from __future__ import annotations

from typing import Callable


def _default_publish(agent: str, text: str) -> None:
    del agent, text


def _default_unread(repo: str) -> str:
    del repo
    return ""


def publish_chat(agent: str, text: str, transport: Callable[[str, str], None] | None = None) -> None:
    """Publish through an optional transport without breaking coordination."""
    transport = transport or _default_publish
    try:
        transport(agent, text)
    except Exception:  # noqa: BLE001 - chat is best-effort; it must never break a coordination action
        return


def show_unread(repo, transport: Callable[[str], str] | None = None) -> str:
    """Return an optional transport's unread-message banner."""
    transport = transport or _default_unread
    try:
        return transport(str(repo)) or ""
    except Exception:  # noqa: BLE001 - best-effort surface; never break the command that triggered it
        return ""
