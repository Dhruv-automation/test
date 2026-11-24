"""Health route unit tests."""

from fastapi.routing import APIRoute

from app.api.health import health_check, router
from main import app


def test_health_route_is_registered_and_returns_minimal_response() -> None:
    route = next(
        route
        for route in router.routes
        if isinstance(route, APIRoute) and route.path == "/health"
    )

    assert "GET" in route.methods
    assert route.endpoint is health_check
    assert "/health" in app.openapi()["paths"]
    assert health_check() == {"status": "ok"}
