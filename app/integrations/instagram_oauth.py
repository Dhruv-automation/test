"""Server-side OAuth service for Meta's Instagram Login flow."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode, urlsplit

import httpx
from dotenv import load_dotenv

from app.security.credential_vault import CredentialVault, CredentialVaultError

INSTAGRAM_AUTHORIZE_URL = "https://www.instagram.com/oauth/authorize"
INSTAGRAM_CODE_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
INSTAGRAM_GRAPH_BASE_URL = "https://graph.instagram.com"
INSTAGRAM_REFRESH_URL = f"{INSTAGRAM_GRAPH_BASE_URL}/refresh_access_token"

SUPPORTED_SCOPES = frozenset(
    {
        "instagram_business_basic",
        "instagram_business_content_publish",
        "instagram_business_manage_comments",
        "instagram_business_manage_messages",
    }
)
DEFAULT_SCOPES = ("instagram_business_basic",)
CALLBACK_PATH = "/auth/meta/callback"
CONNECTION_CREDENTIAL_NAME = "instagram_connection"
APP_SECRET_CREDENTIAL_NAME = "meta_app_secret"


class InstagramOAuthError(RuntimeError):
    """Base error with no provider response or credential content."""


class InstagramOAuthConfigurationError(InstagramOAuthError):
    """Raised when local Meta OAuth settings are missing or invalid."""


class InstagramOAuthExchangeError(InstagramOAuthError):
    """Raised when Meta rejects or cannot complete an OAuth exchange."""


@dataclass(frozen=True)
class InstagramOAuthSettings:
    app_id: str | None
    redirect_uri: str
    scopes: tuple[str, ...] = DEFAULT_SCOPES
    api_version: str = "v27.0"

    @classmethod
    def from_environment(cls) -> "InstagramOAuthSettings":
        project_root = Path(__file__).resolve().parents[2]
        load_dotenv(project_root / ".env", override=False)

        scope_text = os.getenv("INSTAGRAM_OAUTH_SCOPES", ",".join(DEFAULT_SCOPES))
        scopes = tuple(part.strip() for part in scope_text.split(",") if part.strip())
        return cls(
            app_id=os.getenv("INSTAGRAM_APP_ID") or None,
            redirect_uri=os.getenv(
                "INSTAGRAM_REDIRECT_URI",
                "http://127.0.0.1:8000/auth/meta/callback",
            ),
            scopes=scopes,
            api_version=os.getenv("INSTAGRAM_API_VERSION", "v27.0"),
        )

    def validate(self) -> None:
        if not self.app_id or not self.app_id.isdigit():
            raise InstagramOAuthConfigurationError("Set a valid INSTAGRAM_APP_ID in the local .env file.")

        try:
            parsed = urlsplit(self.redirect_uri)
        except ValueError:
            raise InstagramOAuthConfigurationError("Instagram redirect URI is invalid.") from None
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"127.0.0.1", "localhost"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path != CALLBACK_PATH
        ):
            raise InstagramOAuthConfigurationError(
                "Use a loopback redirect URI ending in /auth/meta/callback."
            )
        if parsed.scheme != "https" and parsed.hostname != "127.0.0.1" and parsed.hostname != "localhost":
            raise InstagramOAuthConfigurationError("OAuth redirect URI must use HTTPS.")
        if not re.fullmatch(r"v\d+\.\d+", self.api_version):
            raise InstagramOAuthConfigurationError("INSTAGRAM_API_VERSION must look like v27.0.")
        if not self.scopes or "instagram_business_basic" not in self.scopes:
            raise InstagramOAuthConfigurationError("instagram_business_basic is required.")
        if len(set(self.scopes)) != len(self.scopes) or not set(self.scopes).issubset(SUPPORTED_SCOPES):
            raise InstagramOAuthConfigurationError("INSTAGRAM_OAUTH_SCOPES contains an unsupported scope.")


@dataclass(frozen=True)
class InstagramConnectionSummary:
    user_id: str
    permissions: tuple[str, ...]
    expires_at: datetime


class InstagramOAuthService:
    """Build authorization URLs and exchange codes without exposing tokens."""

    def __init__(
        self,
        settings: InstagramOAuthSettings,
        *,
        vault_factory: Callable[[], CredentialVault] = CredentialVault,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.settings = settings
        self._vault_factory = vault_factory
        self._transport = transport

    def authorization_url(self, state: str) -> str:
        self.settings.validate()
        if not state or len(state) > 256:
            raise InstagramOAuthConfigurationError("OAuth state is invalid.")

        query = urlencode(
            {
                "client_id": self.settings.app_id,
                "redirect_uri": self.settings.redirect_uri,
                "response_type": "code",
                "scope": ",".join(self.settings.scopes),
                "state": state,
                "enable_fb_login": "false",
            }
        )
        return f"{INSTAGRAM_AUTHORIZE_URL}?{query}"

    def complete_authorization(self, authorization_code: str) -> InstagramConnectionSummary:
        self.settings.validate()
        if not authorization_code or len(authorization_code) > 4096:
            raise InstagramOAuthExchangeError("Meta returned an invalid authorization code.")

        vault = self._vault_factory()
        try:
            app_secret = vault.get_secret(APP_SECRET_CREDENTIAL_NAME)
        except CredentialVaultError:
            raise InstagramOAuthConfigurationError("Meta App Secret is unavailable in Windows Credential Manager.") from None
        if not app_secret:
            raise InstagramOAuthConfigurationError("Store the Meta App Secret in Windows Credential Manager first.")

        timeout = httpx.Timeout(20.0, connect=5.0)
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=timeout,
                follow_redirects=False,
            ) as client:
                short_response = client.post(
                    INSTAGRAM_CODE_TOKEN_URL,
                    files={
                        "client_id": (None, self.settings.app_id or ""),
                        "client_secret": (None, app_secret),
                        "grant_type": (None, "authorization_code"),
                        "redirect_uri": (None, self.settings.redirect_uri),
                        "code": (None, authorization_code),
                    },
                )
                short_response.raise_for_status()
                short_lived = self._parse_short_lived_response(short_response.json())
                if "instagram_business_basic" not in short_lived["permissions"]:
                    raise InstagramOAuthExchangeError("The account did not grant the required basic permission.")

                long_response = client.get(
                    f"{INSTAGRAM_GRAPH_BASE_URL}/access_token",
                    params={
                        "grant_type": "ig_exchange_token",
                        "client_secret": app_secret,
                        "access_token": short_lived["access_token"],
                    },
                )
                long_response.raise_for_status()
                long_lived = self._parse_long_lived_response(long_response.json())
        except InstagramOAuthError:
            raise
        except Exception:
            # Provider URLs and bodies may contain codes or tokens; never surface them.
            raise InstagramOAuthExchangeError("Meta token exchange failed.") from None

        expires_at = datetime.now(timezone.utc) + timedelta(seconds=long_lived["expires_in"])
        connection = {
            "access_token": long_lived["access_token"],
            "user_id": short_lived["user_id"],
            "permissions": list(short_lived["permissions"]),
            "issued_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        try:
            vault.set_secret(
                CONNECTION_CREDENTIAL_NAME,
                json.dumps(connection, separators=(",", ":")),
            )
        except CredentialVaultError:
            raise InstagramOAuthExchangeError("The token could not be stored in Windows Credential Manager.") from None

        return InstagramConnectionSummary(
            user_id=short_lived["user_id"],
            permissions=short_lived["permissions"],
            expires_at=expires_at,
        )

    def refresh_connection(self) -> InstagramConnectionSummary:
        """Refresh an eligible long-lived token and replace the stored bundle."""
        vault = self._vault_factory()
        try:
            raw_connection = vault.get_secret(CONNECTION_CREDENTIAL_NAME)
        except CredentialVaultError:
            raise InstagramOAuthConfigurationError("Instagram connection is unavailable in Windows Credential Manager.") from None
        if not raw_connection:
            raise InstagramOAuthConfigurationError("No Instagram connection is stored.")

        try:
            connection = json.loads(raw_connection)
            issued_at = datetime.fromisoformat(connection["issued_at"])
            expires_at = datetime.fromisoformat(connection["expires_at"])
            access_token = connection["access_token"]
            user_id = connection["user_id"]
            permissions_value = connection["permissions"]
            if issued_at.tzinfo is None or expires_at.tzinfo is None:
                raise ValueError
            if (
                not isinstance(access_token, str)
                or not access_token
                or not isinstance(user_id, str)
                or not isinstance(permissions_value, list)
                or any(not isinstance(item, str) for item in permissions_value)
            ):
                raise ValueError
            permissions = tuple(permissions_value)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise InstagramOAuthConfigurationError("Stored Instagram connection metadata is invalid.") from None

        now = datetime.now(timezone.utc)
        if now >= expires_at:
            raise InstagramOAuthConfigurationError("Instagram token expired; reconnect the account.")
        if now - issued_at < timedelta(hours=24):
            raise InstagramOAuthConfigurationError("Instagram token can be refreshed after it is 24 hours old.")
        if "instagram_business_basic" not in permissions:
            raise InstagramOAuthConfigurationError("Instagram basic permission is required to refresh this token.")

        try:
            with httpx.Client(
                transport=self._transport,
                timeout=httpx.Timeout(20.0, connect=5.0),
                follow_redirects=False,
            ) as client:
                response = client.get(
                    INSTAGRAM_REFRESH_URL,
                    params={
                        "grant_type": "ig_refresh_token",
                        "access_token": access_token,
                    },
                )
                response.raise_for_status()
                refreshed = self._parse_long_lived_response(response.json())
        except InstagramOAuthError:
            raise
        except Exception:
            raise InstagramOAuthExchangeError("Meta token refresh failed.") from None

        new_expires_at = now + timedelta(seconds=refreshed["expires_in"])
        connection["access_token"] = refreshed["access_token"]
        connection["issued_at"] = now.isoformat()
        connection["expires_at"] = new_expires_at.isoformat()
        try:
            vault.set_secret(
                CONNECTION_CREDENTIAL_NAME,
                json.dumps(connection, separators=(",", ":")),
            )
        except CredentialVaultError:
            raise InstagramOAuthExchangeError("The refreshed token could not be stored securely.") from None

        return InstagramConnectionSummary(
            user_id=user_id,
            permissions=permissions,
            expires_at=new_expires_at,
        )

    @staticmethod
    def _parse_short_lived_response(payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise InstagramOAuthExchangeError("Meta returned an invalid token response.")
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != 1 or not isinstance(data[0], dict):
            raise InstagramOAuthExchangeError("Meta returned an invalid token response.")
        entry = data[0]
        access_token = entry.get("access_token")
        user_id = entry.get("user_id")
        permissions_value = entry.get("permissions")
        if not isinstance(access_token, str) or not access_token:
            raise InstagramOAuthExchangeError("Meta returned an invalid token response.")
        if not isinstance(user_id, (str, int)) or not str(user_id):
            raise InstagramOAuthExchangeError("Meta returned an invalid token response.")
        if not isinstance(permissions_value, str):
            raise InstagramOAuthExchangeError("Meta returned an invalid permission response.")
        permissions = tuple(
            sorted({item.strip() for item in permissions_value.split(",") if item.strip()})
        )
        return {"access_token": access_token, "user_id": str(user_id), "permissions": permissions}

    @staticmethod
    def _parse_long_lived_response(payload: object) -> dict[str, object]:
        if not isinstance(payload, dict):
            raise InstagramOAuthExchangeError("Meta returned an invalid long-lived token response.")
        access_token = payload.get("access_token")
        expires_in = payload.get("expires_in")
        token_type = payload.get("token_type")
        if (
            not isinstance(access_token, str)
            or not access_token
            or type(expires_in) is not int
            or expires_in <= 0
            or token_type != "bearer"
        ):
            raise InstagramOAuthExchangeError("Meta returned an invalid long-lived token response.")
        return {"access_token": access_token, "expires_in": expires_in}
