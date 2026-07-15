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


__all__ = ["daily_report_job"]
