"""Optional Bearer-token authentication for dangerous endpoints.

Design:
- When `settings.auth_api_key` is empty (default for local dev), `require_api_key`
  is a no-op — every request passes. This keeps the existing localhost workflow
  working without any setup.
- When set, the dependency requires `Authorization: Bearer <key>` to match the
  configured value (constant-time comparison).
- Health, market data, and config endpoints are NOT protected — only the
  endpoints that can move money or change engine state are wired through this
  dependency at the route level.

This is intentionally minimal: no JWT, no scopes, no roles. It's a single
shared secret kept in `.env`. If the deployment ever needs multi-user auth
or external exposure, swap this module for a richer scheme (OAuth2 / API
key per client / mTLS) — the route wiring stays the same.
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, Request, status


def require_api_key(
    request: Request,
    authorization: str | None = Header(default=None),
) -> None:
    """FastAPI dependency that enforces the optional API key.

    Reads the configured `auth_api_key` from `app.state.trading.settings`
    (set by `create_app`'s lifespan hook). When the value is empty the
    dependency passes immediately. When set, a missing or wrong token
    raises 401.
    """

    state = request.app.state.trading
    expected: str = state.settings.auth_api_key
    if not expected:
        return  # auth disabled

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header (expected `Bearer <token>`)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not secrets.compare_digest(token.strip(), expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )
