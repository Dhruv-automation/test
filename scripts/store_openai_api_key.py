"""Prompt without echo and save the OpenAI API key to Windows Credential Manager."""

from __future__ import annotations

from getpass import getpass

from app.agents.campaign_planner import OPENAI_API_KEY_CREDENTIAL_NAME
from app.security.credential_vault import CredentialVault
from app.security.runtime_guard import secure_runtime_issue


def main() -> None:
    runtime_issue = secure_runtime_issue()
    if runtime_issue:
        raise SystemExit(runtime_issue)
    api_key = getpass("OpenAI API key (input hidden): ")
    if not api_key or not api_key.strip():
        raise SystemExit("No API key entered; nothing was stored.")

    CredentialVault().set_secret(OPENAI_API_KEY_CREDENTIAL_NAME, api_key)
    print("OpenAI API key saved in Windows Credential Manager.")


if __name__ == "__main__":
    main()
