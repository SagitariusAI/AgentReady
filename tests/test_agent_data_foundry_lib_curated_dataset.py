# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from agent_data_foundry_lib.curated_dataset import curated_dataset_root


def test_curated_dataset_root_path_is_stable():
    root = Path("X:/repo")
    p = curated_dataset_root(root)
    # the Dataset path string is an output-path contract; it must not drift
    assert p == root / "data" / "training-library" / "30_curated" / "internal" / "factory-dataset"
    assert p.name == "factory-dataset"


def test_reexported_identity_from_agent_data_foundry_and_training_export():
    import agent_data_foundry as adf
    from agent_data_foundry_lib import training_export

    # agent_data_foundry re-exports the dataset path leaf
    assert adf.curated_dataset_root is curated_dataset_root
    # training_export imports it from dataset.py at module level (no longer a lazy central import)
    assert training_export.curated_dataset_root is curated_dataset_root
