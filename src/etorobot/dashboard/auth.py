# src/etorobot/dashboard/auth.py
from __future__ import annotations

import secrets as _secrets
from collections.abc import Awaitable, Callable

from fastapi import HTTPException, Request


def _extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:]
    q = request.query_params.get("token")
    if q:
        return q
    return request.cookies.get("dashboard_token")


def make_auth(token: str | None) -> Callable[[Request], Awaitable[None]]:
    """Build a FastAPI dependency enforcing a single shared token.

    If ``token`` is None (not configured), auth is disabled — intended only
    for local development. Production deployments MUST set DASHBOARD_TOKEN.
    """

    async def require_token(request: Request) -> None:
        if token is None:
            return
        provided = _extract_token(request)
        if provided is None or not _secrets.compare_digest(provided, token):
            raise HTTPException(status_code=401, detail="unauthorized")

    return require_token
