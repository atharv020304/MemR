"""
MemR Vault Manager — create, list, delete, and select vaults.

Each vault is a directory under .memr/vaults/ containing a vault.json
metadata file and a snapshots/ subdirectory.
"""

from __future__ import annotations
import json
import shutil
from datetime import date
from pathlib import Path

from memr.types import Vault


class VaultManager:
    def __init__(self, memory_root: str):
        self.memory_root = Path(memory_root)
        self.vaults_dir = self.memory_root / "vaults"
        self._selected: set[str] = set()

    # ── Init ─────────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """Ensure the vaults directory exists."""
        self.vaults_dir.mkdir(parents=True, exist_ok=True)

    # ── CRUD ─────────────────────────────────────────────────────────────

    async def create(self, name: str, description: str | None = None) -> Vault:
        """Create a new vault with its directory structure."""
        vault_path = self.vaults_dir / name

        if vault_path.exists():
            raise FileExistsError(f'Vault "{name}" already exists')

        vault_path.mkdir(parents=True)
        (vault_path / "snapshots").mkdir()

        today = date.today().isoformat()
        vault = Vault(
            name=name,
            path=str(vault_path),
            description=description,
            created=today,
            updated=today,
        )

        meta_path = vault_path / "vault.json"
        meta_path.write_text(
            json.dumps(vault.__dict__, indent=2),
            encoding="utf-8",
        )
        return vault

    async def get(self, name: str) -> Vault | None:
        """Get a vault by name, or None if it doesn't exist."""
        vault_path = self.vaults_dir / name
        if not vault_path.is_dir():
            return None

        meta_path = vault_path / "vault.json"
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            return Vault(**data)
        except (FileNotFoundError, json.JSONDecodeError):
            return Vault(name=name, path=str(vault_path))

    async def list_all(self) -> list[Vault]:
        """List every vault with its metadata."""
        if not self.vaults_dir.exists():
            return []

        vaults: list[Vault] = []
        for entry in sorted(self.vaults_dir.iterdir()):
            if entry.is_dir():
                meta_path = entry / "vault.json"
                try:
                    data = json.loads(meta_path.read_text(encoding="utf-8"))
                    vaults.append(Vault(**data))
                except (FileNotFoundError, json.JSONDecodeError):
                    vaults.append(Vault(name=entry.name, path=str(entry)))
        return vaults

    async def delete(self, name: str) -> None:
        """Permanently remove a vault and all its snapshots."""
        vault_path = self.vaults_dir / name
        if not vault_path.exists():
            raise FileNotFoundError(f'Vault "{name}" not found')

        shutil.rmtree(vault_path)
        self._selected.discard(name)

    async def update_metadata(self, name: str, **updates: str) -> None:
        """Patch vault metadata fields (description, updated, etc.)."""
        vault = await self.get(name)
        if not vault:
            raise FileNotFoundError(f'Vault "{name}" not found')

        data = vault.__dict__.copy()
        data.update(updates)
        data["updated"] = date.today().isoformat()

        meta_path = Path(vault.path) / "vault.json"
        meta_path.write_text(
            json.dumps(data, indent=2),
            encoding="utf-8",
        )

    # ── Selection ────────────────────────────────────────────────────────

    def select(self, names: list[str]) -> None:
        self._selected = set(names)

    def get_selected(self) -> list[str]:
        return sorted(self._selected)

    def get_vault_path(self, name: str) -> Path:
        return self.vaults_dir / name