"""把 Engine API 返回的 dict 格式化为 Bot 消息文本（HTML）。"""

from __future__ import annotations

from typing import Any


def _esc(text: Any) -> str:
    """HTML 转义。"""
    s = str(text) if text is not None else ""
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_status(data: dict[str, Any]) -> str:
    running = data.get("running", False)
    emoji = "🟢" if running else "🔴"
    exchanges = data.get("exchanges", [])
    strategies = data.get("strategies", [])
    risk = data.get("risk", {})
    daily_pnl = risk.get("daily_pnl", 0)
    drawdown = risk.get("current_drawdown_pct", 0) or risk.get("current_drawdown", 0)
    kill = risk.get("kill_switch_enabled", False)
    positions = data.get("positions", {})
    pos_count = positions.get("count", 0) if isinstance(positions, dict) else 0
    monitor = data.get("monitor", {})
    alerts = monitor.get("total_alerts", 0) if isinstance(monitor, dict) else 0
    runner = data.get("signal_runner", {})
    runner_on = runner.get("running", False) if isinstance(runner, dict) else False

    lines = [
        f"{emoji} <b>引擎状态</b>",
        f"运行: {'是' if running else '否'}",
        f"交易所: {_esc(', '.join(exchanges) or '无')}",
        f"策略: {_esc(', '.join(strategies) or '无')} ({len(strategies)} 个)",
        f"持仓: {pos_count} 个",
        f"日盈亏: <code>{daily_pnl:+.2f}</code> USDT",
        f"回撤: <code>{drawdown * 100:.2f}%</code>" if isinstance(drawdown, (int, float)) else f"回撤: {_esc(drawdown)}",
        f"Kill Switch: {'🚨 已启用' if kill else '正常'}",
        f"信号运行器: {'运行中' if runner_on else '已停止'}",
        f"告警总数: {alerts}",
    ]
    return "\n".join(lines)


def format_paper(data: dict[str, Any]) -> str:
    cash = data.get("cash", 0)
    equity = data.get("equity", 0)
    initial = data.get("initial_cash", 0)
    positions = data.get("positions", [])
    realized = data.get("realized_pnl", 0)
    unrealized = data.get("unrealized_pnl", 0)
    total_pnl = data.get("total_pnl", realized + unrealized)

    lines = [
        "📊 <b>模拟盘</b>",
        f"现金: <code>{cash:.2f}</code> USDT",
        f"权益: <code>{equity:.2f}</code> USDT",
        f"初始: <code>{initial:.2f}</code> USDT",
        f"已实现: <code>{realized:+.2f}</code> USDT",
        f"未实现: <code>{unrealized:+.2f}</code> USDT",
        f"总盈亏: <code>{total_pnl:+.2f}</code> USDT",
    ]
    if positions:
        lines.append(f"持仓品种: {len(positions)}")
        for p in positions[:5]:
            sym = p.get("symbol", "?")
            qty = p.get("quantity", 0)
            entry = p.get("entry_price", 0)
            lines.append(f"  {_esc(sym)} qty={qty} @ {entry}")
    return "\n".join(lines)


def format_positions(data: dict[str, Any]) -> str:
    positions = data.get("positions", [])
    if not positions:
        return "📦 当前无持仓"
    lines = ["📦 <b>当前持仓</b>"]
    for p in positions:
        sym = p.get("symbol", "?")
        side = p.get("side", "")
        qty = p.get("quantity", 0)
        entry = p.get("entry_price", 0)
        mark = p.get("mark_price", 0)
        upnl = p.get("unrealized_pnl", 0)
        lines.append(
            f"{_esc(sym)} {_esc(side)} qty={qty} entry={entry} mark={mark} uPnL={upnl:+.2f}"
        )
    return "\n".join(lines)


def format_signals(data: dict[str, Any]) -> str:
    signals = data.get("signals", [])
    if not signals:
        return "📡 最近无信号"
    lines = ["📡 <b>最近信号</b>"]
    for s in signals[:5]:
        action = s.get("action", "?")
        sym = s.get("symbol", "?")
        strat = s.get("strategy", "?")
        strength = s.get("strength", 0)
        actionable = s.get("actionable", False)
        emoji = "✅" if actionable else "⏸"
        lines.append(f"{emoji} {_esc(action.upper())} {_esc(sym)} [{_esc(strat)}] 强度={strength:.2f}")
    return "\n".join(lines)


def format_strategies(data: dict[str, Any]) -> str:
    strategies = data.get("strategies", [])
    if not strategies:
        return "⚙️ 无已注册策略"
    lines = ["⚙️ <b>策略列表</b>"]
    for s in strategies:
        name = s.get("name", "?")
        cls = s.get("class_name", "?")
        running = s.get("running", False)
        mode = s.get("mode", "signal")
        sym = s.get("symbol", "")
        emoji = "🟢" if running else "⚪"
        lines.append(f"{emoji} {_esc(name)} ({_esc(cls)}) mode={_esc(mode)} sym={_esc(sym)}")
    return "\n".join(lines)


def format_events(data: dict[str, Any]) -> str:
    events = data.get("events", [])
    if not events:
        return "📜 最近无审计事件"
    lines = ["📜 <b>最近事件</b>"]
    for e in events[:8]:
        etype = e.get("event_type", "?")
        msg = e.get("message", "")
        level = e.get("level", "info")
        ts = e.get("timestamp", "")[:19]
        lines.append(f"[{_esc(level)}] {_esc(etype)}: {_esc(msg)} ({ts})")
    return "\n".join(lines)


def format_risk(data: dict[str, Any]) -> str:
    kill = data.get("kill_switch_enabled", False)
    daily = data.get("daily_pnl", 0)
    dd = data.get("current_drawdown_pct", 0) or data.get("current_drawdown", 0)
    orders = data.get("orders_last_minute", 0)
    max_orders = data.get("max_orders_per_minute", 0)
    trading = data.get("trading_enabled", True)
    lines = [
        "🛡 <b>风控状态</b>",
        f"交易权限: {'允许' if trading else '禁止'}",
        f"Kill Switch: {'🚨 启用' if kill else '正常'}",
        f"日盈亏: <code>{daily:+.2f}</code> USDT",
    ]
    if isinstance(dd, (int, float)):
        lines.append(f"回撤: <code>{dd * 100:.2f}%</code>")
    lines.append(f"下单频率: {orders}/{max_orders} 单/分钟")
    return "\n".join(lines)


def format_ticker(symbol: str, data: dict[str, Any]) -> str:
    price = data.get("last_price", 0)
    change = data.get("price_change_pct_24h", 0)
    vol = data.get("volume_24h", 0)
    emoji = "📈" if change >= 0 else "📉"
    return (
        f"{emoji} <b>{_esc(symbol)}</b>\n"
        f"价格: <code>{price}</code>\n"
        f"24h 涨跌: <code>{change:+.2f}%</code>\n"
        f"24h 量: <code>{vol}</code>"
    )
