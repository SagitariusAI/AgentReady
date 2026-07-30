from __future__ import annotations

from pathlib import Path

from agent_data_foundry_lib.dojo import inhouse_dojo_root


def test_inhouse_dojo_root_path_is_stable():
    root = Path("X:/repo")
    p = inhouse_dojo_root(root)
    # the Dojo path string is an output-path contract; it must not drift
    assert p == root / "data" / "training-library" / "30_curated" / "internal" / "factory-dojo"
    assert p.name == "factory-dojo"


def test_reexported_identity_from_agent_data_foundry_and_training_export():
    import agent_data_foundry as adf
    from agent_data_foundry_lib import training_export

    # agent_data_foundry re-exports the dojo path leaf
    assert adf.inhouse_dojo_root is inhouse_dojo_root
    # training_export imports it from dojo.py at module level (no longer a lazy central import)
    assert training_export.inhouse_dojo_root is inhouse_dojo_root
