# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Public support for   init  ."""
from __future__ import annotations

from agent_coordination.chat import publish_chat, show_unread
from agent_coordination.common import new_task_id, now_stamp, slug
from agent_coordination.events import add_event
from agent_coordination.locks import remove_locks, set_locks
from agent_coordination.paths import (
    normalize_path,
    path_conflicts,
    path_overlap,
    protected_path_intent,
    protected_surface,
    to_path_list,
)
from agent_coordination.quality import (
    claim_quality,
    handoff_quality,
    quality_failure_message,
    task_start_quality,
    text_length,
)
from agent_coordination.store import ensure_state, state_dir, worktree_path
from agent_coordination.tasks import ACTIVE_STATUSES, get_tasks, read_task, task_path, write_task

__all__ = [
    "ensure_state", "state_dir", "worktree_path",
    "task_path", "read_task", "write_task", "get_tasks", "ACTIVE_STATUSES",
    "add_event",
    "normalize_path", "to_path_list", "path_overlap", "path_conflicts",
    "protected_surface", "protected_path_intent",
    "set_locks", "remove_locks",
    "task_start_quality", "claim_quality", "handoff_quality", "quality_failure_message", "text_length",
    "publish_chat", "show_unread",
    "new_task_id", "slug", "now_stamp",
]
