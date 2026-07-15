"""Bot 命令处理器 — 通过 Engine API 查询和操作。

每个 handler 签名: async (api: BotApiClient, args: list[str], chat_id: int) -> str
返回 HTML 格式的消息文本。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx

from app.bot import formatter
from app.bot.config import BotConfig


class BotApiClient:
    """对 Engine API 的轻量封装。

    每次请求都会注入 ``X-Bot-Scope``（默认 ``monitor``），让服务器端的
    ScopeContextMiddleware 能在 access log 中区分 bot 调用和 web-ui 调用。
    认证仍然复用 ``auth_api_key``，但服务端日志可以通过 scope 看出
    "这个 /api/v1/risk/kill-switch 是从 bot 触发的"。
    """

    def __init__(self, config: BotConfig) -> None:
        self._base = config.api_base_url.rstrip("/")
        self._timeout = config.request_timeout_seconds
        self._headers: dict[str, str] = {
            # 标记调用来源。app.api.middleware.ScopeContextMiddleware
            # 会把它写到每条访问日志里。
            "X-Bot-Scope": config.outbound_scope,
        }
        if config.api_key:
            self._headers["Authorization"] = f"Bearer {config.api_key}"

    async def get(self, path: str, **params: Any) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self._base}{path}", params=params, headers=self._headers
            )
            resp.raise_for_status()
            return resp.json()

    async def post(self, path: str, json_data: dict | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base}{path}", json=json_data or {}, headers=self._headers
            )
            resp.raise_for_status()
            return resp.json()

    async def delete(self, path: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.delete(f"{self._base}{path}", headers=self._headers)
            resp.raise_for_status()
            return resp.json()


# ── 命令处理函数 ──────────────────────────────────────────────


async def cmd_help(api: BotApiClient, args: list[str], chat_id: int) -> str:
    return (
        "🤖 <b>可用命令</b>\n"
        "/status — 引擎状态\n"
        "/pnl — 模拟盘盈亏\n"
        "/positions — 当前持仓\n"
        "/signals — 最近信号\n"
        "/strategies — 策略列表\n"
        "/risk — 风控状态\n"
        "/kill — 查看 kill switch\n"
        "/kill on [reason] — 启用 kill switch\n"
        "/kill off [reason] — 关闭 kill switch\n"
        "/ticker SYMBOL — 查行情 (默认 BTCUSDT)\n"
        "/events — 最近审计事件\n"
        "/runner — 信号运行器状态\n"
        "/start_strategy NAME — 启用策略\n"
        "/stop_strategy NAME — 停用策略\n"
        "/help — 本帮助"
    )


async def cmd_status(api: BotApiClient, args: list[str], chat_id: int) -> str:
    data = await api.get("/api/v1/engine/status")
    return formatter.format_status(data)


async def cmd_pnl(api: BotApiClient, args: list[str], chat_id: int) -> str:
    data = await api.get("/api/v1/paper")
    return formatter.format_paper(data)


async def cmd_positions(api: BotApiClient, args: list[str], chat_id: int) -> str:
    data = await api.get("/api/v1/engine/status")
    return formatter.format_positions(data.get("positions", {}))


async def cmd_signals(api: BotApiClient, args: list[str], chat_id: int) -> str:
    data = await api.get("/api/v1/signals/recent", limit=5)
    return formatter.format_signals(data)


async def cmd_strategies(api: BotApiClient, args: list[str], chat_id: int) -> str:
    data = await api.get("/api/v1/strategies")
    return formatter.format_strategies(data)


async def cmd_risk(api: BotApiClient, args: list[str], chat_id: int) -> str:
    data = await api.get("/api/v1/engine/status")
    return formatter.format_risk(data.get("risk", {}))


async def cmd_events(api: BotApiClient, args: list[str], chat_id: int) -> str:
    data = await api.get("/api/v1/events/recent", limit=8)
    return formatter.format_events(data)


async def cmd_runner(api: BotApiClient, args: list[str], chat_id: int) -> str:
    data = await api.get("/api/v1/runner/status")
    running = data.get("running", False)
    cycles = data.get("cycles", 0)
    sigs = data.get("signals_generated", 0)
    last_err = data.get("last_error")
    last_cycle = data.get("last_cycle_at", "")
    emoji = "🟢" if running else "⚪"
    text = (
        f"{emoji} <b>信号运行器</b>\n"
        f"运行: {'是' if running else '否'}\n"
        f"周期数: {cycles}\n"
        f"信号数: {sigs}\n"
        f"最近: {last_cycle[:19] if last_cycle else '无'}"
    )
    if last_err:
        text += f"\n错误: {_esc(last_err)}"
    return text


def _esc(text: Any) -> str:
    s = str(text) if text is not None else ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def cmd_kill(api: BotApiClient, args: list[str], chat_id: int) -> str:
    if not args:
        data = await api.get("/api/v1/risk/kill-switch")
        enabled = data.get("enabled", False)
        reason = data.get("reason", "")
        emoji = "🚨" if enabled else "✅"
        return f"{emoji} Kill Switch: {'启用' if enabled else '关闭'}\n原因: {_esc(reason)}"
    action = args[0].lower()
    if action not in ("on", "off"):
        return "用法: /kill on [reason] 或 /kill off [reason]"
    reason = " ".join(args[1:]) if len(args) > 1 else "bot_manual"
    enabled = action == "on"
    data = await api.post(
        "/api/v1/risk/kill-switch",
        json_data={"enabled": enabled, "reason": reason},
    )
    return f"{'🚨' if enabled else '✅'} Kill Switch 已{'启用' if enabled else '关闭'}\n原因: {_esc(reason)}"


async def cmd_ticker(api: BotApiClient, args: list[str], chat_id: int) -> str:
    symbol = args[0].upper() if args else "BTCUSDT"
    try:
        data = await api.get("/api/v1/ticker/binance_usdm", symbol=symbol)
        return formatter.format_ticker(symbol, data)
    except Exception as exc:
        return f"❌ 查询 {symbol} 失败: {_esc(exc)}"


async def cmd_start_strategy(api: BotApiClient, args: list[str], chat_id: int) -> str:
    if not args:
        return "用法: /start_strategy NAME"
    name = args[0]
    try:
        await api.post(f"/api/v1/strategies/{name}/start")
        return f"✅ 策略 {_esc(name)} 已启用"
    except Exception as exc:
        return f"❌ 启用失败: {_esc(exc)}"


async def cmd_stop_strategy(api: BotApiClient, args: list[str], chat_id: int) -> str:
    if not args:
        return "用法: /stop_strategy NAME"
    name = args[0]
    try:
        await api.post(f"/api/v1/strategies/{name}/stop")
        return f"⚪ 策略 {_esc(name)} 已停用"
    except Exception as exc:
        return f"❌ 停用失败: {_esc(exc)}"


# ── 命令路由表 ──────────────────────────────────────────────

CommandHandler = Callable[[BotApiClient, list[str], int], "object"]

COMMANDS: dict[str, CommandHandler] = {
    "/help": cmd_help,
    "/status": cmd_status,
    "/pnl": cmd_pnl,
    "/positions": cmd_positions,
    "/signals": cmd_signals,
    "/strategies": cmd_strategies,
    "/risk": cmd_risk,
    "/kill": cmd_kill,
    "/ticker": cmd_ticker,
    "/events": cmd_events,
    "/runner": cmd_runner,
    "/start_strategy": cmd_start_strategy,
    "/stop_strategy": cmd_stop_strategy,
}


async def dispatch(
    text: str, api: BotApiClient, chat_id: int
) -> str | None:
    """解析命令文本，路由到对应 handler。"""
    parts = text.split()
    if not parts:
        return None
    cmd = parts[0].lower()
    handler = COMMANDS.get(cmd)
    if handler is None:
        return f"未知命令: {_esc(cmd)}\n输入 /help 查看可用命令"
    args = parts[1:]
    try:
        result = await handler(api, args, chat_id)
        return str(result)
    except httpx.HTTPStatusError as exc:
        return f"❌ API 错误 ({exc.response.status_code}): {_esc(exc.response.text[:200])}"
    except Exception as exc:
        return f"❌ 执行失败: {_esc(exc)}"
