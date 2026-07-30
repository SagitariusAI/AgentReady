# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess

import agent_runtime_paths as arp


def _git_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init"], cwd=str(path), capture_output=True, check=True)
    return path


def test_state_root_shape_and_location():
    root = arp.state_root(".")
    assert root.parent == arp.COORDINATION_ROOT
    name, digest = root.name.rsplit("-", 1)
    assert len(digest) == 16 and all(c in "0123456789abcdef" for c in digest)
    assert name  # non-empty repo name


def test_state_root_is_deterministic(tmp_path):
    repo = _git_repo(tmp_path / "r")
    assert arp.state_root(repo) == arp.state_root(repo)


def test_state_root_differs_per_repo(tmp_path):
    a = _git_repo(tmp_path / "a")
    b = _git_repo(tmp_path / "b")
    assert arp.state_root(a) != arp.state_root(b)


def test_repo_name_uses_git_owner(tmp_path):
    repo = _git_repo(tmp_path / "myrepo")
    assert arp.repo_name(arp.resolve_repo(repo)) == "myrepo"


def test_git_common_dir_none_outside_repo(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    assert arp.git_common_dir(arp.resolve_repo(plain)) is None


def test_store_layout_constants():
    assert "tasks" in arp.STORE_SUBDIRS and "events" in arp.STORE_SUBDIRS
    assert len(arp.STORE_SUBDIRS) == 9
    assert arp.COORDINATION_ROOT.name == "coordination"


def test_worktree_root_under_worktrees(tmp_path):
    repo = _git_repo(tmp_path / "wt")
    assert arp.worktree_root(repo).parent == arp.WORKTREE_ROOT
