# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
from pathlib import Path

from agent_data_foundry_lib.paths import (
    AGENTREADY_HOME,
    _current_git_commit,
    claim_evidence_release_root,
    default_release_id,
    report_data_foundry_path,
    run_id_utc,
)
from agent_data_foundry_lib.schemas import CLAIM_EVIDENCE_PRODUCT_ID


def test_path_roots_are_canonical():
    root = Path("R")
    assert report_data_foundry_path(root, "x.json") == root / "reports" / "data-foundry" / "x.json"
    assert claim_evidence_release_root(root) == root / "data" / "training-library" / "40_release_ready" / CLAIM_EVIDENCE_PRODUCT_ID
    assert claim_evidence_release_root(root, "custom-id").name == "custom-id"


def test_agentready_home_is_a_path():
    assert isinstance(AGENTREADY_HOME, Path)


def test_run_and_release_id_formats():
    assert re.fullmatch(r"\d{8}-\d{6}-\d{6}", run_id_utc())  # YYYYmmdd-HHMMSS-microseconds
    assert re.fullmatch(r"\d{8}-\d{6}", default_release_id())


def test_current_git_commit_repo_vs_nongit(tmp_path: Path):
    sha = _current_git_commit(Path.cwd())
    assert sha is None or re.fullmatch(r"[0-9a-f]{40}", sha)  # real repo -> 40-hex; never fabricated
    assert _current_git_commit(tmp_path) is None  # not a git repo -> explicit None


def test_reexported_identity_from_central_and_package():
    import agent_data_foundry as adf
    import agent_data_foundry_lib as adfl

    assert adf.report_data_foundry_path is report_data_foundry_path
    assert adf.AGENTREADY_HOME is AGENTREADY_HOME
    assert adf._current_git_commit is _current_git_commit
    assert adf.claim_evidence_release_root is claim_evidence_release_root
    assert adfl.report_data_foundry_path is report_data_foundry_path
    assert adfl.run_id_utc is run_id_utc
