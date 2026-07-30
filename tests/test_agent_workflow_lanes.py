# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from agent_workflow_lanes import classify_workflow_lane, stamp_workflow_lane


def test_explicit_lane_is_authoritative() -> None:
    assert classify_workflow_lane({"workflow_lane": "personal", "title": "training"}) == (
        "personal",
        "explicit",
    )


def test_dataset_work_is_derived_as_research() -> None:
    lane, source = classify_workflow_lane({"title": "Build a training dataset"})
    assert lane == "research"
    assert source == "derived_legacy_intent"


def test_ordinary_software_work_defaults_to_business() -> None:
    assert stamp_workflow_lane({"title": "Package the finished application"}) == {
        "title": "Package the finished application",
        "workflow_lane": "business",
        "workflow_lane_source": "derived_legacy_default",
    }
