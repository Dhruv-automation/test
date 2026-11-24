"""Windows Credential Manager wrapper.

This module deliberately refuses keyring's fallback backends. Secrets must only
be stored in the Windows Credential Manager backend on the supported host.
"""

from __future__ import annotations

import re

import keyring
from keyring.backends.Windows import WinVaultKeyring, win32cred
from keyring.errors import PasswordDeleteError

DEFAULT_SERVICE_NAME = "instagram-ai-platform"
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")


class CredentialVaultError(RuntimeError):
    """Raised when the secure Windows credential backend is unavailable."""


class CredentialVault:
    """Store application secrets in the current user's Windows Credential Manager."""

    def __init__(self, service_name: str = DEFAULT_SERVICE_NAME) -> None:
        self._validate_identifier(service_name, "service name")

        backend = keyring.get_keyring()
        if not isinstance(backend, WinVaultKeyring):
            raise CredentialVaultError(
                "Windows Credential Manager is unavailable; refusing to use a fallback backend."
            )

        # Keep credentials on this device rather than allowing roaming-profile sync.
        backend.persist = win32cred.CRED_PERSIST_LOCAL_MACHINE
        self._service_name = service_name
        self._backend = backend

    @staticmethod
    def _validate_identifier(value: str, label: str) -> None:
        if not isinstance(value, str) or not _IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError(f"Invalid {label}.")

    def set_secret(self, name: str, secret: str) -> None:
        """Add or replace a secret under a non-secret account name."""
        self._validate_identifier(name, "credential name")
        if not isinstance(secret, str) or not secret or not secret.strip() or "\x00" in secret:
            raise ValueError("Secret must be a non-empty string without NUL characters.")

        try:
            self._backend.set_password(self._service_name, name, secret)
        except Exception:
            # Do not include the secret or backend exception details in user-visible errors.
            raise CredentialVaultError("Windows Credential Manager could not store the secret.") from None

    def get_secret(self, name: str) -> str | None:
        """Return a secret, or None when the named credential is not present."""
        self._validate_identifier(name, "credential name")
        try:
            return self._backend.get_password(self._service_name, name)
        except Exception:
            raise CredentialVaultError("Windows Credential Manager could not read the secret.") from None

    def delete_secret(self, name: str) -> bool:
        """Delete a secret and return whether it existed."""
        self._validate_identifier(name, "credential name")
        try:
            self._backend.delete_password(self._service_name, name)
            return True
        except PasswordDeleteError:
            return False
        except Exception:
            raise CredentialVaultError("Windows Credential Manager could not delete the secret.") from None
