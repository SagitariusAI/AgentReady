# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import agent_router


def test_public_profiles_only_reference_public_commands():
    allowed = set(agent_router.MODULE_FALLBACKS)
    for profile in agent_router.PROFILES:
        for item in agent_router.build_plan(profile):
            assert str(item["command"]).split()[0] in allowed


def test_release_selection_and_plan_are_deterministic():
    assert agent_router.select_profile("package a public release") == "release"
    first = agent_router.build_plan("release")
    second = agent_router.build_plan("release")
    assert first == second
    assert any(item["command"] == "agent-publication-guard" for item in first)
    assert any(item["command"] == "agent-package-public" for item in first)


def test_module_fallback_resolves_every_public_command(monkeypatch):
    monkeypatch.setattr(agent_router.shutil, "which", lambda _name: None)
    for command in agent_router.MODULE_FALLBACKS:
        resolved = agent_router.resolve_step_command(command)
        assert resolved is not None
        assert resolved[1] == "-m"
