"""
Auto-provision vaults when none is selected or a named vault is missing.
"""

from __future__ import annotations

import logging

from memr.vault.manager import VaultManager

logger = logging.getLogger("memr.vault.auto")

DEFAULT_VAULT_NAME = "default"


class AutoProvisioner:
    def __init__(self, vault_mgr: VaultManager):
        self.vault_mgr = vault_mgr

    async def ensure_vault(self, vault_name: str | None = None) -> str:
        await self.vault_mgr.initialize()

        if vault_name:
            existing = await self.vault_mgr.get(vault_name)
            if existing:
                self.vault_mgr.select([vault_name])
                return vault_name
            vault = await self.vault_mgr.create(
                vault_name, "Auto-created by MemR"
            )
            self.vault_mgr.select([vault.name])
            logger.info("Auto-created vault %r", vault.name)
            return vault.name

        selected = self.vault_mgr.get_selected()
        if selected:
            return selected[0]

        vaults = await self.vault_mgr.list_all()
        if vaults:
            best = max(vaults, key=lambda v: (v.updated or "", v.name))
            self.vault_mgr.select([best.name])
            return best.name

        vault = await self.vault_mgr.create(
            DEFAULT_VAULT_NAME, "Auto-created default vault"
        )
        self.vault_mgr.select([vault.name])
        logger.info("Auto-created default vault %r", vault.name)
        return vault.name
