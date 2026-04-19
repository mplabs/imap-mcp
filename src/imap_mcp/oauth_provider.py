"""File-backed OAuth 2.0 authorization server provider for imap-mcp.

Stores all OAuth state (clients, auth codes, tokens) in a single JSON file
at ~/.local/state/imap-mcp/oauth.json. Writes are atomic (write-to-tmp, rename).

The authorize() method redirects to the setup wizard (/setup?oauth_state=<nonce>)
where the user enters IMAP credentials. The wizard calls create_auth_code() on
success, which completes the OAuth authorization code flow.
"""

from __future__ import annotations

import json
import secrets
import time
from pathlib import Path
from typing import Optional

from pydantic import AnyUrl

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


_DEFAULT_STATE_PATH = Path.home() / ".local" / "state" / "imap-mcp" / "oauth.json"

_EMPTY: dict = {
    "clients": {},
    "auth_codes": {},
    "access_tokens": {},
    "refresh_tokens": {},
    "pending_auth": {},  # nonce → serialised AuthorizationParams for setup wizard
}


class JsonFileOAuthProvider(OAuthAuthorizationServerProvider):
    """Implements OAuthAuthorizationServerProvider with JSON file storage."""

    def __init__(self, state_path: Optional[Path] = None, setup_path: str = "/setup") -> None:
        self._path = state_path or _DEFAULT_STATE_PATH
        self._setup_path = setup_path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write(_EMPTY.copy())

    # ------------------------------------------------------------------
    # Storage helpers
    # ------------------------------------------------------------------

    def _read(self) -> dict:
        try:
            data = json.loads(self._path.read_text())
            # Back-fill any keys added after first write
            for key, default in _EMPTY.items():
                data.setdefault(key, type(default)())
            return data
        except (json.JSONDecodeError, FileNotFoundError):
            return {k: type(v)() for k, v in _EMPTY.items()}

    def _write(self, data: dict) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, default=str))
        tmp.replace(self._path)

    # ------------------------------------------------------------------
    # OAuthAuthorizationServerProvider protocol
    # ------------------------------------------------------------------

    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        raw = self._read()["clients"].get(client_id)
        if raw is None:
            return None
        return OAuthClientInformationFull.model_validate(raw)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        data = self._read()
        data["clients"][client_info.client_id] = client_info.model_dump(mode="json")
        self._write(data)

    async def authorize(
        self,
        client: OAuthClientInformationFull,
        params: AuthorizationParams,
    ) -> str:
        """Store the pending OAuth params and redirect to the setup wizard."""
        nonce = secrets.token_urlsafe(32)
        data = self._read()
        data["pending_auth"][nonce] = {
            "client_id": client.client_id,
            "redirect_uri": str(params.redirect_uri),
            "redirect_uri_provided_explicitly": params.redirect_uri_provided_explicitly,
            "state": params.state,
            "scopes": params.scopes or [],
            "code_challenge": params.code_challenge,
            "expires_at": time.time() + 600,  # 10-minute window
        }
        self._write(data)
        return f"{self._setup_path}?oauth_state={nonce}"

    async def load_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: str,
    ) -> Optional[AuthorizationCode]:
        raw = self._read()["auth_codes"].get(authorization_code)
        if raw is None:
            return None
        return AuthorizationCode(
            code=raw["code"],
            scopes=raw["scopes"],
            expires_at=raw["expires_at"],
            client_id=raw["client_id"],
            code_challenge=raw["code_challenge"],
            redirect_uri=AnyUrl(raw["redirect_uri"]),
            redirect_uri_provided_explicitly=raw["redirect_uri_provided_explicitly"],
            resource=raw.get("resource"),
        )

    async def exchange_authorization_code(
        self,
        client: OAuthClientInformationFull,
        authorization_code: AuthorizationCode,
    ) -> OAuthToken:
        data = self._read()
        data["auth_codes"].pop(authorization_code.code, None)

        access_token = secrets.token_urlsafe(32)
        refresh_tok = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + 3600  # 1 hour

        data["access_tokens"][access_token] = {
            "token": access_token,
            "client_id": client.client_id,
            "scopes": authorization_code.scopes,
            "expires_at": expires_at,
        }
        data["refresh_tokens"][refresh_tok] = {
            "token": refresh_tok,
            "client_id": client.client_id,
            "scopes": authorization_code.scopes,
            "expires_at": None,
        }
        self._write(data)

        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=3600,
            refresh_token=refresh_tok,
            scope=" ".join(authorization_code.scopes),
        )

    async def load_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: str,
    ) -> Optional[RefreshToken]:
        raw = self._read()["refresh_tokens"].get(refresh_token)
        if raw is None:
            return None
        return RefreshToken(
            token=raw["token"],
            client_id=raw["client_id"],
            scopes=raw["scopes"],
            expires_at=raw.get("expires_at"),
        )

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        data = self._read()
        data["refresh_tokens"].pop(refresh_token.token, None)

        effective_scopes = scopes or refresh_token.scopes
        access_token = secrets.token_urlsafe(32)
        new_refresh = secrets.token_urlsafe(32)
        expires_at = int(time.time()) + 3600

        data["access_tokens"][access_token] = {
            "token": access_token,
            "client_id": client.client_id,
            "scopes": effective_scopes,
            "expires_at": expires_at,
        }
        data["refresh_tokens"][new_refresh] = {
            "token": new_refresh,
            "client_id": client.client_id,
            "scopes": effective_scopes,
            "expires_at": None,
        }
        self._write(data)

        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=3600,
            refresh_token=new_refresh,
            scope=" ".join(effective_scopes),
        )

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        raw = self._read()["access_tokens"].get(token)
        if raw is None:
            return None
        return AccessToken(
            token=raw["token"],
            client_id=raw["client_id"],
            scopes=raw["scopes"],
            expires_at=raw.get("expires_at"),
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        data = self._read()
        t = token.token
        data["access_tokens"].pop(t, None)
        data["refresh_tokens"].pop(t, None)
        self._write(data)

    # ------------------------------------------------------------------
    # Setup wizard helpers
    # ------------------------------------------------------------------

    def pop_pending_auth(self, nonce: str) -> Optional[dict]:
        """Return and remove the pending auth params for a nonce. None if expired/missing."""
        data = self._read()
        pending = data["pending_auth"].get(nonce)
        if pending is None:
            return None
        if pending["expires_at"] < time.time():
            del data["pending_auth"][nonce]
            self._write(data)
            return None
        del data["pending_auth"][nonce]
        self._write(data)
        return pending

    def create_auth_code(self, pending: dict) -> str:
        """Create and store an authorization code from consumed pending auth params."""
        code = secrets.token_urlsafe(32)
        data = self._read()
        data["auth_codes"][code] = {
            "code": code,
            "client_id": pending["client_id"],
            "redirect_uri": pending["redirect_uri"],
            "redirect_uri_provided_explicitly": pending["redirect_uri_provided_explicitly"],
            "state": pending["state"],
            "scopes": pending["scopes"],
            "code_challenge": pending["code_challenge"],
            "expires_at": time.time() + 120,  # 2-minute exchange window
            "resource": None,
        }
        self._write(data)
        return code
