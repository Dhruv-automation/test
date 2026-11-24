# Instagram AI Platform

Local-first development scaffold for an approval-based Instagram management platform. The application will bind to `127.0.0.1` by default. Instagram account operations will use Meta's official APIs only.

## Current setup status

- Project folder and Git repository created.
- `.gitignore` excludes local secrets, database files, generated media, and logs.
- Python 3.12.10 remains installed for compatibility checks; the secure project environment is Python 3.14.10 in `.venv314`.
- The patched venv has FastAPI, LangGraph, the OpenAI SDK, and the project dependencies installed.
- The credential vault, health route, and unit tests are implemented.
- Instagram Business Login OAuth routes and mocked token exchange/refresh tests are implemented.
- A LangGraph Content Director workflow creates structured campaign drafts, runs lightweight QA, retries once, and stops at human approval.

## Project checklist

- [x] Python 3.12.10 and Git verified; patched Python 3.14.10 venv and dependencies installed.
- [x] Git ignore rules cover environment secrets, credentials, databases, generated media, and logs.
- [x] Credential vault implementation rejects insecure keyring fallback backends.
- [x] FastAPI `/health` route binds through a localhost-only runner.
- [x] Unit tests pass for vault behavior and health route wiring.
- [x] Windows Defender and all firewall profiles confirmed enabled; C: is fully encrypted and protection is on.
- [x] Windows Credential Manager integration test passed in a normal PowerShell session.
- [x] Local HTTP request to `/health` returned `status: ok`.
- [x] Instagram OAuth state, code exchange, token storage, and refresh logic are implemented with mocked tests.
- [x] LangGraph campaign planning, QA retry, and approval-required API route implemented; all workflow tests use offline planner stubs.
- [x] Current test result: 35 passed, 1 skipped; the skipped test is the opt-in Credential Manager integration test.
- [ ] Add SQLite persistence for brand profiles and campaign approval status.
- [ ] Configure the Meta developer app and run the OAuth round-trip with the user's own Creator account.

Python 3.12.10 is the last Python 3.12 release with a full Windows installer. The current 3.12.16 release includes security fixes but is source-only. Python 3.14.10 has a Windows installer and those fixes. OAuth routes enforce a patched runtime and return HTTP 503 on older or unreviewed Python builds. The project uses `.venv314` for OAuth and campaign planning. See the [Python 3.12.16 release](https://www.python.org/downloads/release/python-31216/) and [Python 3.14.10 release](https://www.python.org/downloads/release/python-31410/).

## Enable OAuth on a patched Python runtime

The official 64-bit Python 3.14.10 Windows installer is required for OAuth and AI-backed campaign planning. The patched venv is already created on this laptop. To recreate it in a normal PowerShell window:

```powershell
Set-Location "$env:USERPROFILE\Documents\Codex\instagram-ai-platform"
$python314 = "$env:LOCALAPPDATA\Programs\Python\Python314\python.exe"
& $python314 --version
& $python314 -m venv .venv314
.\.venv314\Scripts\python.exe -m pip install --upgrade pip
.\.venv314\Scripts\python.exe -m pip install -r requirements.txt
.\.venv314\Scripts\python.exe -m pytest -q
```

Use `.venv314\Scripts\python.exe` for the app and scripts. If the installer used a different path, substitute the Python 3.14.10 executable path shown by the installer.

## Windows security baseline

Before running the app, confirm these settings in Windows Security and Settings:

1. Windows Security → Virus & threat protection → Manage settings: keep Real-time protection and Cloud-delivered protection on.
2. Windows Security → Firewall & network protection: Microsoft Defender Firewall should be on for each active network profile.
3. Settings → Privacy & security → Device encryption (or BitLocker Drive Encryption): use device encryption if supported, and store the recovery key somewhere separate from this laptop.
4. Keep Windows Update current. Run this app as your normal user, not as Administrator.

You can inspect the current state from PowerShell (some devices require an elevated shell for these read-only status queries):

```powershell
Get-MpComputerStatus | Select-Object AntivirusEnabled, RealTimeProtectionEnabled, IoavProtectionEnabled
Get-NetFirewallProfile | Select-Object Name, Enabled
Get-BitLockerVolume -MountPoint $env:SystemDrive | Select-Object MountPoint, VolumeStatus, ProtectionStatus, EncryptionPercentage
```

The user confirmed Defender, real-time protection, and IOAV protection are on; Domain, Private, and Public firewalls are enabled; and C: reports `FullyEncrypted`, `ProtectionStatus: On`, and 100% encryption.

The credential vault only accepts `WinVaultKeyring`, refuses fallback backends, and configures credentials for local-machine persistence rather than roaming-profile persistence. The Codex sandbox denies calls to the Windows Credential Manager API; run the opt-in integration test in a normal PowerShell session before storing real credentials.

## Create the virtual environment

After installing the official Python 3.12 Windows runtime for your user, open PowerShell:

```powershell
Set-Location "$env:USERPROFILE\Documents\Codex\instagram-ai-platform"
$python312 = "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe"
& $python312 --version
& $python312 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

These commands use the venv interpreter directly and do not require changing PowerShell's execution policy.

## Run locally

```powershell
Set-Location "$env:USERPROFILE\Documents\Codex\instagram-ai-platform"
\.venv314\Scripts\python.exe main.py
```

The server binds to `127.0.0.1:8000`. Check `http://127.0.0.1:8000/health`; it returns `{"status":"ok"}` and exposes no credential or service details.

In a second PowerShell window, verify it with:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

## Tests

Run the test suite with the patched venv:

```powershell
\.venv314\Scripts\python.exe -m pytest -q
```

The default suite uses an in-memory Windows-backend double and mocked Meta responses. It does not call Meta or write test credentials to the user's credential store. The real Windows Credential Manager round-trip test is opt-in and stores only a temporary dummy value:

```powershell
$env:RUN_WINDOWS_VAULT_INTEGRATION = "1"
\.venv314\Scripts\python.exe -m pytest -q -m integration
Remove-Item Env:\RUN_WINDOWS_VAULT_INTEGRATION -ErrorAction SilentlyContinue
```

Run that integration test in a normal PowerShell session outside the Codex sandbox. It passed in `.venv314`; the sandbox itself denies access to the Windows Credential Manager API.

## Campaign planning workflow

`POST /api/campaigns/plan` sends the natural-language instruction and brand profile to OpenAI using Structured Outputs, then runs the result through a LangGraph QA workflow. The workflow retries once when its basic checks find issues and returns either `pending_approval` or `needs_revision`. No publishing or Instagram API action exists in this workflow, and these first drafts are not yet saved to SQLite.

The OpenAI key stays in Windows Credential Manager. Store it from normal PowerShell with:

```powershell
Set-Location "$env:USERPROFILE\Documents\Codex\instagram-ai-platform"
\.venv314\Scripts\python.exe -m scripts.store_openai_api_key
```

Start the local app with `.venv314\Scripts\python.exe main.py`, then open `http://127.0.0.1:8000/docs` and try `POST /api/campaigns/plan`. A successful request uses OpenAI API credits and returns a draft that still requires human approval. Automated tests use an offline planner stub and make no OpenAI API calls.

## Configure Meta OAuth

Meta's Instagram Login flow supports Creator and Business accounts and does not require a Facebook Page. Create a **Business** type Meta app, add the Instagram product, and configure Business Login. For your own account, use Standard Access and add your account as an app role or tester as the dashboard requires. Advanced Access and App Review are required when serving accounts you do not own or manage. See [Meta's Business Login guide](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login) and [Get Started guide](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started).

The code requests only `instagram_business_basic` by default. Add `instagram_business_content_publish`, `instagram_business_manage_comments`, or `instagram_business_manage_messages` to `INSTAGRAM_OAUTH_SCOPES` only when implementing and reviewing those features. The configured API version is `v27.0`, the current version shown in Meta's Get Started guide.

1. Copy `.env.example` to `.env`, fill in the Instagram App ID, and register the exact redirect URI from `.env` in Meta's Business Login settings. The redirect URI is restricted to loopback so the app does not send an OAuth code to a public endpoint.
2. In normal PowerShell, store the Meta App Secret without putting it in `.env`:

   ```powershell
   Set-Location "$env:USERPROFILE\Documents\Codex\instagram-ai-platform"
   .\.venv314\Scripts\python.exe -m scripts.store_meta_app_secret
   ```

   The prompt hides the input and saves it in Windows Credential Manager.
3. Start the local app with `\.venv314\Scripts\python.exe main.py`, then open `http://127.0.0.1:8000/auth/meta/start` in the same computer's browser. Access logs are disabled so the one-time callback code is not written to the local server log.

The callback validates a short-lived, HttpOnly, SameSite=Lax state cookie; exchanges the one-time code server-side; exchanges the short-lived token for a long-lived token; and stores one token bundle in Windows Credential Manager. The browser receives only a connection status message. Meta says long-lived tokens last 60 days and may be refreshed once at least 24 hours old while still valid. The refresh method enforces those conditions; a later scheduler phase will call it. Unit tests use mock responses and never use live Meta credentials.
