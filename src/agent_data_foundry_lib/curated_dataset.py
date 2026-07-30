# Copyright (c) 2026 Sagittarius AI
# Project Owner: Alex Burca
# SPDX-License-Identifier: Apache-2.0

"""Curated Dataset path/root helpers for the Agent Data Foundry."""
from __future__ import annotations

from pathlib import Path


def curated_dataset_root(root: Path) -> Path:
    return root / "data" / "training-library" / "30_curated" / "internal" / "factory-dataset"
