"""
MemR Vault Context — bundles a writer, loader, and compactor for one vault.

Created lazily by the server when a vault is first accessed in a session.
"""

from __future__ import annotations
from pathlib import Path

from memr.types import VaultConfig
from memr.snapshot.writer import SnapshotWriter
from memr.snapshot.loader import SnapshotLoader
from memr.snapshot.compactor import Compactor


class VaultContext:
    """All runtime state scoped to a single vault."""

    def __init__(self, memory_root: str, vault_name: str):
        vault_path = Path(memory_root) / "vaults" / vault_name
        snapshots_dir = vault_path / "snapshots"

        self.config = VaultConfig(
            memory_root=memory_root,
            vault_name=vault_name,
            vault_path=str(vault_path),
        )

        self.writer = SnapshotWriter(vault_name, snapshots_dir)
        self.loader = SnapshotLoader(vault_name, snapshots_dir)
        self.compactor = Compactor(vault_name, snapshots_dir)