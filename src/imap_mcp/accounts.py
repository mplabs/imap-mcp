"""Account registry — central lookup for account configurations."""

from __future__ import annotations

from typing import Optional

from .config import Config, AccountConfig


class AccountRegistry:
    """Holds all configured accounts and resolves the default."""

    def __init__(self, config: Config):
        self._config = config

    @property
    def default_name(self) -> str:
        return self._config.default_account

    def get(self, name: Optional[str] = None) -> AccountConfig:
        """Return the AccountConfig for *name*, or the default if name is None."""
        target = name if name is not None else self._config.default_account
        try:
            return self._config.accounts[target]
        except KeyError:
            raise KeyError(f"Account '{target}' not found in config")

    def list_names(self) -> list[str]:
        return list(self._config.accounts.keys())

    def resolve(self, account: Optional[str]) -> tuple[str, AccountConfig]:
        """Return (name, config) — defaulting to the default account."""
        name = account if account is not None else self._config.default_account
        return name, self.get(name)
