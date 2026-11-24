"""Minimal liveness endpoint with no credential or service details."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    """Return a minimal liveness response."""
    return {"status": "ok"}
