"""Local Instagram Business Login routes."""

from __future__ import annotations

import hmac
import logging
import secrets
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import PlainTextResponse, RedirectResponse

from app.integrations.instagram_oauth import (
    InstagramOAuthConfigurationError,
    InstagramOAuthError,
    InstagramOAuthService,
    InstagramOAuthSettings,
)
from app.security.runtime_guard import oauth_runtime_issue

router = APIRouter(prefix="/auth/meta", tags=["meta-oauth"])
logger = logging.getLogger(__name__)
STATE_COOKIE_NAME = "instagram_oauth_state"
STATE_COOKIE_PATH = "/auth/meta"
STATE_MAX_AGE_SECONDS = 600


def get_oauth_service() -> InstagramOAuthService:
    runtime_issue = oauth_runtime_issue()
    if runtime_issue:
        raise HTTPException(status_code=503, detail=runtime_issue)
    return InstagramOAuthService(InstagramOAuthSettings.from_environment())


def _set_security_headers(response: Response) -> Response:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


def begin_login(request: Request, service: InstagramOAuthService) -> Response:
    state = secrets.token_urlsafe(32)
    try:
        authorization_url = service.authorization_url(state)
    except InstagramOAuthConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from None

    response = RedirectResponse(authorization_url, status_code=302)
    response.set_cookie(
        key=STATE_COOKIE_NAME,
        value=state,
        max_age=STATE_MAX_AGE_SECONDS,
        path=STATE_COOKIE_PATH,
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="lax",
    )
    return _set_security_headers(response)


def _clear_state_cookie(response: Response, request: Request) -> Response:
    response.delete_cookie(
        key=STATE_COOKIE_NAME,
        path=STATE_COOKIE_PATH,
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="lax",
    )
    return _set_security_headers(response)


def _states_match(state: str | None, cookie_state: str | None) -> bool:
    if not isinstance(state, str) or not isinstance(cookie_state, str):
        return False
    if not state or len(state) > 256 or len(cookie_state) > 256:
        return False
    try:
        state.encode("ascii")
        cookie_state.encode("ascii")
    except UnicodeEncodeError:
        return False
    return hmac.compare_digest(state, cookie_state)


def handle_callback(
    request: Request,
    service: InstagramOAuthService,
    *,
    authorization_code: str | None,
    state: str | None,
    provider_error: str | None,
) -> Response:
    cookie_state = request.cookies.get(STATE_COOKIE_NAME)
    if not _states_match(state, cookie_state):
        logger.warning("Rejected Instagram OAuth callback with invalid state.")
        response = PlainTextResponse("Instagram authorization could not be validated.", status_code=400)
        return _clear_state_cookie(response, request)

    if provider_error:
        logger.info("Instagram authorization was declined or canceled.")
        response = PlainTextResponse("Instagram authorization was canceled.", status_code=400)
        return _clear_state_cookie(response, request)

    if not authorization_code:
        response = PlainTextResponse("Instagram authorization did not return a code.", status_code=400)
        return _clear_state_cookie(response, request)

    try:
        service.complete_authorization(authorization_code)
    except InstagramOAuthConfigurationError:
        logger.error("Instagram OAuth configuration or credential storage is unavailable.")
        response = PlainTextResponse("Instagram connection is not configured securely.", status_code=503)
        return _clear_state_cookie(response, request)
    except InstagramOAuthError:
        logger.error("Instagram OAuth token exchange failed.")
        response = PlainTextResponse("Instagram authorization failed. No token was returned to the browser.", status_code=502)
        return _clear_state_cookie(response, request)

    logger.info("Instagram account connected; token stored in Windows Credential Manager.")
    response = RedirectResponse("/auth/meta/connected", status_code=303)
    return _clear_state_cookie(response, request)


@router.get("/start", include_in_schema=False)
def start_instagram_login(
    request: Request,
    service: Annotated[InstagramOAuthService, Depends(get_oauth_service)],
) -> Response:
    return begin_login(request, service)


@router.get("/callback", include_in_schema=False)
def instagram_callback(
    request: Request,
    service: Annotated[InstagramOAuthService, Depends(get_oauth_service)],
    code: Annotated[str | None, Query(max_length=4096)] = None,
    state: Annotated[str | None, Query(max_length=256)] = None,
    error: Annotated[str | None, Query(max_length=128)] = None,
) -> Response:
    return handle_callback(
        request,
        service,
        authorization_code=code,
        state=state,
        provider_error=error,
    )


@router.get("/connected", include_in_schema=False)
def connection_complete() -> Response:
    response = PlainTextResponse(
        "Instagram is connected. The access token is stored in Windows Credential Manager."
    )
    return _set_security_headers(response)
