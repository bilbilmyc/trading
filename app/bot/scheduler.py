"""Bot 调度：每日报告 + 静默时段。

每个调度任务都是 ``async def job(bot: TradingBot) -> None``，
方便测试时直接 ``await scheduler(bot)``，不需要真起 loop。

调用方（main.py 或测试）负责：

- 构造 ``BotAlertSubscriber(cfg, bot.push_to_all)`` 并传给 ``TradingBot``，
- 把 ``[daily_report_job]`` 当作 schedule_jobs 传给 ``TradingBot``，
- bot.stop() 取消所有 job（runner 负责 cleanup）。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from app.bot.runner import TradingBot


async def daily_report_job(bot: TradingBot) -> None:
    """每隔 30 秒检查一次，到点就推日报。循环到 bot.stop()。

    用 ``asyncio.sleep`` 而不是 cron，因为这是单进程/单机部署，
    cron expression 反而更复杂。
    """
    cfg = bot.config
    if not cfg.daily_report_enabled:
        return
    last_sent_date: str | None = None
    logger.info(
        f"Bot daily-report scheduler started "
        f"(hour={cfg.daily_report_hour}, minute={cfg.daily_report_minute})"
    )

    while True:
        try:
            now = datetime.now()
            if (
                now.hour == cfg.daily_report_hour
                and now.minute == cfg.daily_report_minute
            ):
                today = now.date().isoformat()
                if last_sent_date != today:
                    await _send_daily_report(bot)
                    last_sent_date = today
            await asyncio.sleep(30.0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"daily-report scheduler error: {exc!r}")
            await asyncio.sleep(60.0)


async def _send_daily_report(bot: TradingBot) -> None:
    """拉一次 paper + risk + positions，组合成日报推给白名单。"""
    try:
        status = await bot.api.get("/api/v1/engine/status")
        paper = await bot.api.get("/api/v1/paper")
    except Exception as exc:
        logger.warning(f"daily-report fetch failed: {exc!r}")
        return

    risk = (status or {}).get("risk", {})
    text = (
        "📅 <b>每日报告</b> "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"日盈亏: <code>{risk.get('daily_pnl', 0):+.2f}</code> USDT\n"
        f"回撤: <code>{risk.get('current_drawdown_pct', 0) * 100:.2f}%</code>\n"
        f"现金: <code>{paper.get('cash', 0):.2f}</code> USDT\n"
        f"权益: <code>{paper.get('equity', 0):.2f}</code> USDT\n"
        f"已实现: <code>{paper.get('realized_pnl', 0):+.2f}</code> USDT\n"
        f"未实现: <code>{paper.get('unrealized_pnl', 0):+.2f}</code> USDT"
    )
    await bot.push_to_all(text)
    logger.info(
        f"Bot daily report sent at {datetime.now().isoformat(timespec='seconds')}"
    )


async def autopilot_job(bot: TradingBot) -> None:
    """Periodically analyze configured symbols and alert on strict consensus.

    The scheduler itself never talks to an exchange. The API owns market-data
    reads, audit persistence, budget enforcement, risk checks and the optional
    order submission. This keeps the long-polling Bot process low-privilege and
    makes a failed scheduler iteration fail closed.
    """
    cfg = bot.config
    if not cfg.autopilot_enabled:
        return

    logger.info(
        "Bot autopilot scheduler started "
        f"(exchange={cfg.autopilot_exchange}, symbols={','.join(cfg.autopilot_symbols)}, "
        f"cycle={cfg.autopilot_cycle_seconds}s, live_orders={cfg.autopilot_live_order_enabled})"
    )
    last_handled_signal_keys: dict[str, str] = {}
    while True:
        try:
            for symbol in cfg.autopilot_symbols:
                analysis = await bot.api.get(
                    "/api/v1/bot/autopilot/analysis",
                    exchange=cfg.autopilot_exchange,
                    symbol=symbol,
                )
                action = str(analysis.get("action") or "observe").lower()
                if action not in {"buy", "sell"}:
                    continue
                signal_key = str(analysis.get("signal_key") or "")
                if not signal_key:
                    logger.warning(f"Bot autopilot response has no signal key for {symbol}; skipping")
                    continue
                if last_handled_signal_keys.get(symbol) == signal_key:
                    continue
                last_handled_signal_keys[symbol] = signal_key

                lines = [
                    "🤖 <b>Bot 多周期共识信号</b>",
                    f"标的: <code>{analysis.get('symbol', symbol)}</code>",
                    f"动作: <b>{action.upper()}</b>",
                    f"置信度: <code>{float(analysis.get('confidence') or 0):.2%}</code>",
                    f"原因: <code>{analysis.get('reason', 'unknown')}</code>",
                ]
                if cfg.autopilot_live_order_enabled:
                    try:
                        order = await bot.api.post(
                            "/api/v1/bot/autopilot/order",
                            {
                                "exchange": cfg.autopilot_exchange,
                                "symbol": symbol,
                                "side": action,
                                "notional": cfg.autopilot_max_order_notional,
                                "decision_id": analysis["decision_id"],
                            },
                        )
                        lines.append(
                            "订单: <b>已提交</b> "
                            f"(<code>{float(order.get('notional') or 0):.2f} USDT</code>)"
                        )
                    except Exception as exc:
                        # Do not retry in this cycle. A request after submission can
                        # have an unknown outcome; server-side idempotency and
                        # reconciliation are the source of truth.
                        lines.append(f"订单: <b>未提交</b> <code>{type(exc).__name__}</code>")
                        logger.warning(f"Bot autopilot order failed for {symbol}: {exc!r}")
                else:
                    lines.append("订单: <b>仅告警</b>（自动下单双开关未开启）")
                await bot.push_to_all("\n".join(lines))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(f"autopilot scheduler error: {exc!r}")
        await asyncio.sleep(float(cfg.autopilot_cycle_seconds))


__all__ = ["autopilot_job", "daily_report_job"]
