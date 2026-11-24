"""Prompt for the Meta App Secret without echoing it and store it in WinCred."""

from __future__ import annotations

from getpass import getpass

from app.security.credential_vault import CredentialVault
from app.integrations.instagram_oauth import APP_SECRET_CREDENTIAL_NAME
from app.security.runtime_guard import secure_runtime_issue


def main() -> None:
    runtime_issue = secure_runtime_issue()
    if runtime_issue:
        raise SystemExit(runtime_issue)
    secret = getpass("Meta App Secret (input hidden): ")
    if not secret or not secret.strip():
        raise SystemExit("No secret entered; nothing was stored.")

    CredentialVault().set_secret(APP_SECRET_CREDENTIAL_NAME, secret)
    print("Meta App Secret saved in Windows Credential Manager.")


if __name__ == "__main__":
    main()
