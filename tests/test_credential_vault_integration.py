"""Opt-in test against the current user's Windows Credential Manager.

Run outside the Codex sandbox with RUN_WINDOWS_VAULT_INTEGRATION=1. The test
stores only a short-lived dummy value and deletes it in a finally block.
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from app.security.credential_vault import CredentialVault


@pytest.mark.integration
@pytest.mark.skipif(
    os.environ.get("RUN_WINDOWS_VAULT_INTEGRATION") != "1",
    reason="Set RUN_WINDOWS_VAULT_INTEGRATION=1 to access Windows Credential Manager.",
)
def test_windows_credential_manager_round_trip() -> None:
    vault = CredentialVault(service_name=f"instagram-ai-platform-it-{uuid4().hex}")
    name = "dummy-integration-token"
    dummy_secret = "temporary-not-a-real-token"
    stored = False

    try:
        vault.set_secret(name, dummy_secret)
        stored = True
        assert vault.get_secret(name) == dummy_secret
    finally:
        if stored:
            vault.delete_secret(name)

    assert vault.get_secret(name) is None
