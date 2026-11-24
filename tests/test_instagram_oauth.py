"""Mocked tests for the Instagram Login OAuth flow."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from starlette.requests import Request

from app.api.oauth import (
    STATE_COOKIE_NAME,
    begin_login,
    handle_callback,
)
from app.integrations.instagram_oauth import (
    CONNECTION_CREDENTIAL_NAME,
    InstagramOAuthConfigurationError,
    InstagramOAuthExchangeError,
    InstagramOAuthService,
    InstagramOAuthSettings,
)
from app.security.runtime_guard import oauth_runtime_issue


def _settings(**overrides: object) -> InstagramOAuthSettings:
    values: dict[str, object] = {
        "app_id": "123456789012345",
        "redirect_uri": "http://127.0.0.1:8000/auth/meta/callback",
        "scopes": ("instagram_business_basic",),
        "api_version": "v27.0",
    }
    values.update(overrides)
    return InstagramOAuthSettings(**values)  # type: ignore[arg-type]


def _request(path: str, *, cookie: str | None = None, scheme: str = "http") -> Request:
    headers = [(b"host", b"127.0.0.1:8000")]
    if cookie is not None:
        headers.append((b"cookie", cookie.encode("ascii")))
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": scheme,
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 32100),
            "server": ("127.0.0.1", 8000),
        }
    )


class MemoryVault:
    def __init__(self) -> None:
        self.secrets = {"meta_app_secret": "dummy-meta-app-secret"}

    def get_secret(self, name: str) -> str | None:
        return self.secrets.get(name)

    def set_secret(self, name: str, secret: str) -> None:
        self.secrets[name] = secret


class CallbackService:
    def __init__(self) -> None:
        self.received_codes: list[str] = []

    def complete_authorization(self, code: str) -> None:
        self.received_codes.append(code)


@pytest.mark.parametrize(
    ("version", "should_be_blocked"),
    [
        ((3, 12, 10), True),
        ((3, 12, 16), False),
        ((3, 13, 18), False),
        ((3, 14, 10), False),
        ((3, 15, 2), False),
        ((3, 16, 0), True),
    ],
)
def test_runtime_guard_requires_known_security_patched_python_builds(
    version: tuple[int, int, int], should_be_blocked: bool
) -> None:
    issue = oauth_runtime_issue(version)
    assert (issue is not None) is should_be_blocked


def test_oauth_dependency_refuses_unpatched_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import HTTPException

    from app.api import oauth

    monkeypatch.setattr(
        oauth,
        "oauth_runtime_issue",
        lambda: "Instagram OAuth is disabled on this Python build.",
    )
    with pytest.raises(HTTPException) as exc_info:
        oauth.get_oauth_service()
    assert exc_info.value.status_code == 503


def test_authorization_url_uses_only_configured_scopes_and_state() -> None:
    settings = _settings(
        scopes=("instagram_business_basic", "instagram_business_content_publish")
    )
    service = InstagramOAuthService(settings)

    url = urlsplit(service.authorization_url("random-state-value"))
    params = parse_qs(url.query)

    assert url.scheme == "https"
    assert url.netloc == "www.instagram.com"
    assert url.path == "/oauth/authorize"
    assert params["client_id"] == ["123456789012345"]
    assert params["redirect_uri"] == [settings.redirect_uri]
    assert params["response_type"] == ["code"]
    assert params["scope"] == ["instagram_business_basic,instagram_business_content_publish"]
    assert params["state"] == ["random-state-value"]
    assert params["enable_fb_login"] == ["false"]


def test_authorization_rejects_non_loopback_redirect_and_unknown_scope() -> None:
    with pytest.raises(InstagramOAuthConfigurationError):
        InstagramOAuthService(
            _settings(redirect_uri="http://192.168.1.10/auth/meta/callback")
        ).authorization_url("state")

    with pytest.raises(InstagramOAuthConfigurationError):
        InstagramOAuthService(_settings(scopes=("instagram_basic",))).authorization_url("state")


def test_begin_login_sets_short_lived_http_only_lax_state_cookie() -> None:
    service = InstagramOAuthService(_settings())

    response = begin_login(_request("/auth/meta/start"), service)

    assert response.status_code == 302
    state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
    cookie = response.headers["set-cookie"]
    assert len(state) >= 40
    assert STATE_COOKIE_NAME in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert "Path=/auth/meta" in cookie
    assert "Max-Age=600" in cookie
    assert "Cache-Control" in response.headers
    assert "Referrer-Policy" in response.headers


def test_callback_rejects_state_mismatch_without_exchanging_code() -> None:
    service = CallbackService()
    request = _request("/auth/meta/callback", cookie=f"{STATE_COOKIE_NAME}=expected")

    response = handle_callback(
        request,
        service,  # type: ignore[arg-type]
        authorization_code="attacker-controlled-code",
        state="different",
        provider_error=None,
    )

    assert response.status_code == 400
    assert service.received_codes == []
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_callback_rejects_non_ascii_state_safely() -> None:
    service = CallbackService()
    request = _request("/auth/meta/callback", cookie=f"{STATE_COOKIE_NAME}=plain-state")

    response = handle_callback(
        request,
        service,  # type: ignore[arg-type]
        authorization_code="dummy-code",
        state="bad–state",
        provider_error=None,
    )

    assert response.status_code == 400
    assert service.received_codes == []


def test_callback_exchanges_only_after_state_matches() -> None:
    service = CallbackService()
    request = _request("/auth/meta/callback", cookie=f"{STATE_COOKIE_NAME}=same-state")

    response = handle_callback(
        request,
        service,  # type: ignore[arg-type]
        authorization_code="one-time-dummy-code",
        state="same-state",
        provider_error=None,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/auth/meta/connected"
    assert service.received_codes == ["one-time-dummy-code"]


def test_mocked_code_exchange_stores_only_long_lived_token_bundle() -> None:
    vault = MemoryVault()
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.host == "api.instagram.com":
            assert request.method == "POST"
            assert b"authorization_code" in request.content
            assert b"one-time-dummy-code" in request.content
            assert b"dummy-meta-app-secret" in request.content
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "access_token": "short-lived-dummy-token",
                            "user_id": "17840000000000001",
                            "permissions": "instagram_business_basic",
                        }
                    ]
                },
            )
        assert request.url.host == "graph.instagram.com"
        assert request.url.path == "/access_token"
        assert request.url.params["grant_type"] == "ig_exchange_token"
        assert request.url.params["access_token"] == "short-lived-dummy-token"
        assert request.url.params["client_secret"] == "dummy-meta-app-secret"
        return httpx.Response(
            200,
            json={
                "access_token": "long-lived-dummy-token",
                "token_type": "bearer",
                "expires_in": 5184000,
            },
        )

    service = InstagramOAuthService(
        _settings(),
        vault_factory=lambda: vault,  # type: ignore[arg-type]
        transport=httpx.MockTransport(handler),
    )

    result = service.complete_authorization("one-time-dummy-code")
    stored = json.loads(vault.get_secret(CONNECTION_CREDENTIAL_NAME) or "{}")

    assert len(calls) == 2
    assert result.user_id == "17840000000000001"
    assert result.permissions == ("instagram_business_basic",)
    assert stored["access_token"] == "long-lived-dummy-token"
    assert "short-lived-dummy-token" not in json.dumps(stored)
    assert stored["expires_at"] == result.expires_at.isoformat()


def test_exchange_fails_closed_when_basic_permission_was_not_granted() -> None:
    vault = MemoryVault()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "access_token": "short-token",
                        "user_id": "123",
                        "permissions": "instagram_business_manage_comments",
                    }
                ]
            },
        )

    service = InstagramOAuthService(
        _settings(),
        vault_factory=lambda: vault,  # type: ignore[arg-type]
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(InstagramOAuthExchangeError, match="required basic permission"):
        service.complete_authorization("dummy-code")

    assert calls == ["api.instagram.com"]
    assert CONNECTION_CREDENTIAL_NAME not in vault.secrets


def test_refresh_uses_documented_eligibility_and_updates_token_bundle() -> None:
    vault = MemoryVault()
    now = datetime.now(timezone.utc)
    vault.secrets[CONNECTION_CREDENTIAL_NAME] = json.dumps(
        {
            "access_token": "old-long-lived-token",
            "user_id": "17840000000000001",
            "permissions": ["instagram_business_basic"],
            "issued_at": (now - timedelta(hours=48)).isoformat(),
            "expires_at": (now + timedelta(days=12)).isoformat(),
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/refresh_access_token"
        assert request.url.params["grant_type"] == "ig_refresh_token"
        assert request.url.params["access_token"] == "old-long-lived-token"
        return httpx.Response(
            200,
            json={
                "access_token": "refreshed-long-lived-token",
                "token_type": "bearer",
                "expires_in": 5184000,
            },
        )

    service = InstagramOAuthService(
        _settings(),
        vault_factory=lambda: vault,  # type: ignore[arg-type]
        transport=httpx.MockTransport(handler),
    )

    result = service.refresh_connection()
    stored = json.loads(vault.get_secret(CONNECTION_CREDENTIAL_NAME) or "{}")

    assert stored["access_token"] == "refreshed-long-lived-token"
    assert result.user_id == "17840000000000001"
    assert stored["expires_at"] == result.expires_at.isoformat()


def test_refresh_refuses_tokens_younger_than_24_hours() -> None:
    vault = MemoryVault()
    now = datetime.now(timezone.utc)
    vault.secrets[CONNECTION_CREDENTIAL_NAME] = json.dumps(
        {
            "access_token": "new-token",
            "user_id": "123",
            "permissions": ["instagram_business_basic"],
            "issued_at": (now - timedelta(hours=1)).isoformat(),
            "expires_at": (now + timedelta(days=30)).isoformat(),
        }
    )
    service = InstagramOAuthService(
        _settings(),
        vault_factory=lambda: vault,  # type: ignore[arg-type]
        transport=httpx.MockTransport(lambda request: pytest.fail("No refresh request expected")),
    )

    with pytest.raises(InstagramOAuthConfigurationError, match="24 hours old"):
        service.refresh_connection()


def test_refresh_requires_basic_permission() -> None:
    vault = MemoryVault()
    now = datetime.now(timezone.utc)
    vault.secrets[CONNECTION_CREDENTIAL_NAME] = json.dumps(
        {
            "access_token": "old-token",
            "user_id": "123",
            "permissions": ["instagram_business_manage_comments"],
            "issued_at": (now - timedelta(days=2)).isoformat(),
            "expires_at": (now + timedelta(days=30)).isoformat(),
        }
    )
    service = InstagramOAuthService(
        _settings(),
        vault_factory=lambda: vault,  # type: ignore[arg-type]
        transport=httpx.MockTransport(lambda request: pytest.fail("No refresh request expected")),
    )

    with pytest.raises(InstagramOAuthConfigurationError, match="basic permission"):
        service.refresh_connection()
