"""Credential vault unit tests using an in-memory Windows-backend double."""

from __future__ import annotations

from uuid import uuid4

import keyring
import pytest
from keyring.backends.Windows import WinVaultKeyring
from keyring.errors import PasswordDeleteError

from app.security.credential_vault import CredentialVault, CredentialVaultError


@pytest.fixture
def vault(monkeypatch: pytest.MonkeyPatch) -> CredentialVault:
    """Exercise storage behavior without touching the user's credential store."""

    class InMemoryWinVaultKeyring(WinVaultKeyring):
        def __init__(self) -> None:
            self.entries: dict[tuple[str, str], str] = {}

        def set_password(self, service: str, username: str, password: str) -> None:
            self.entries[(service, username)] = password

        def get_password(self, service: str, username: str) -> str | None:
            return self.entries.get((service, username))

        def delete_password(self, service: str, username: str) -> None:
            try:
                del self.entries[(service, username)]
            except KeyError:
                raise PasswordDeleteError from None

    backend = InMemoryWinVaultKeyring()
    monkeypatch.setattr(keyring, "get_keyring", lambda: backend)
    return CredentialVault(service_name=f"instagram-ai-platform-test-{uuid4().hex}")


def test_secret_round_trip_and_idempotent_delete(vault: CredentialVault) -> None:
    dummy_secret = "not-a-real-access-token-7b59d849"

    vault.set_secret("dummy-test-token", dummy_secret)
    assert vault.get_secret("dummy-test-token") == dummy_secret
    assert vault.delete_secret("dummy-test-token") is True
    assert vault.get_secret("dummy-test-token") is None
    assert vault.delete_secret("dummy-test-token") is False


def test_missing_secret_returns_none(vault: CredentialVault) -> None:
    assert vault.get_secret("missing-test-token") is None


@pytest.mark.parametrize("name", ["", "contains spaces", "name/with/slash", "x" * 129])
def test_rejects_invalid_credential_names(vault: CredentialVault, name: str) -> None:
    with pytest.raises(ValueError, match="Invalid credential name"):
        vault.get_secret(name)


@pytest.mark.parametrize("secret", ["", "   ", "invalid\x00secret"])
def test_rejects_invalid_secret_values(vault: CredentialVault, secret: str) -> None:
    with pytest.raises(ValueError, match="Secret must be"):
        vault.set_secret("dummy-test-token", secret)


def test_refuses_non_windows_fallback_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(keyring, "get_keyring", lambda: object())

    with pytest.raises(CredentialVaultError, match="refusing to use a fallback backend"):
        CredentialVault()
