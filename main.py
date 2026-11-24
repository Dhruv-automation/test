"""FastAPI application entry point."""

import logging

from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.campaigns import router as campaigns_router
from app.api.oauth import router as oauth_router

app = FastAPI(
    title="Instagram AI Platform",
    version="0.1.0",
    redoc_url=None,
)
app.include_router(health_router)
app.include_router(campaigns_router)
app.include_router(oauth_router)

# OAuth callback URLs contain one-time authorization codes in their query string.
logging.getLogger("uvicorn.access").disabled = True


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, access_log=False)
