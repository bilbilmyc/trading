"""HTTP 中间件：可选的请求 scope 标签。

``X-Bot-Scope`` 头标记出 "是谁在调这个 API"。典型的值：

  - ``web-ui``    —— 前端 SPA 直接调用
  - ``bot``       —— Telegram bot 监控盯盘在调
  - ``external``  —— 第三方脚本（Curl / Postman）
  - 未设置       —— 浏览器手动访问，无明确来源

中间件把它记录到 ``request.state.scope``，并在响应后用 loguru 打一行
INFO 访问日志，把来源、端点、方法、状态码、耗时都拢在一行，便于 grep
调查 "这个 kill switch 是谁触发的"。
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from loguru import logger
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class ScopeContextMiddleware(BaseHTTPMiddleware):
    """Attach ``request.state.scope`` and emit an access-log line per response.

    The header value ``X-Bot-Scope`` (case-insensitive) is the only input.
    Anything except health/metrics/openapi/docs gets logged — those are
    spammy enough to skip.
    """

    SKIP_PATHS: frozenset[str] = frozenset({
        "/health",
        "/healthz",
        "/metrics",
        "/favicon.ico",
    })

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        scope = request.headers.get("x-bot-scope") or "anonymous"
        request.state.scope = scope

        path = request.url.path
        skip = (
            path in self.SKIP_PATHS
            or path.startswith("/docs")
            or path.startswith("/redoc")
            or path.startswith("/openapi")
        )

        if skip:
            return await call_next(request)

        start = time.monotonic()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            logger.info(
                "access scope={} method={} path={} status={} elapsed_ms={:.1f}",
                scope,
                request.method,
                path,
                status_code,
                elapsed_ms,
            )


__all__ = ["ScopeContextMiddleware"]
