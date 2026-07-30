# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Canonical personal/business/research workflow-lane classification.

Code remains Factory machinery. The lane belongs to the work and its data.
Training and dataset creation are always research. Historical records that
predate the explicit field receive a deterministic derived classification.
"""
from __future__ import annotations

import re
from typing import Any

WORKFLOW_LANES = ("personal", "business", "research")

_RESEARCH = re.compile(
    r"\b(research|training|train|dataset|data[ -]?foundry|data[ -]?forge|"
    r"fine[ -]?tun|evaluation|benchmark|model[ -]?card|curriculum|dataset)\b",
    re.IGNORECASE,
)
_PERSONAL = re.compile(
    r"\b(personal|private creative|closed creative|studio_share)\b",
    re.IGNORECASE,
)


def classify_workflow_lane(record: dict[str, Any]) -> tuple[str, str]:
    """Return ``(lane, source)`` using explicit metadata before legacy inference."""
    explicit = str(record.get("workflow_lane") or "").strip().lower()
    if explicit:
        if explicit not in WORKFLOW_LANES:
            raise ValueError(
                f"workflow_lane must be one of {', '.join(WORKFLOW_LANES)}; got {explicit!r}"
            )
        return explicit, str(record.get("workflow_lane_source") or "explicit")

    blob = " ".join(
        str(record.get(field) or "")
        for field in (
            "title",
            "intent",
            "intent_summary",
            "summary",
            "task_class",
            "collection_purpose",
            "dataset_format_target",
        )
    )
    if _PERSONAL.search(blob):
        return "personal", "derived_legacy_intent"
    if _RESEARCH.search(blob):
        return "research", "derived_legacy_intent"
    return "business", "derived_legacy_default"


def stamp_workflow_lane(record: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy with canonical lane metadata."""
    stamped = dict(record)
    lane, source = classify_workflow_lane(stamped)
    stamped["workflow_lane"] = lane
    stamped["workflow_lane_source"] = source
    return stamped
