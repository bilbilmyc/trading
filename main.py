"""
Command entry point for the Web3 trading system.
"""

import argparse
import asyncio
from collections.abc import Sequence

from app.exchanges.factory import ExchangeFactory
from config import Settings, load_settings


def build_engine(settings: Settings):
    """Build a trading engine from settings.

    Imports are kept inside the function so lightweight commands such as
    `python main.py status` still work before all runtime dependencies are
    installed.
    """

    from app.engine.risk_manager import RiskConfig
    from app.engine.trader import TradingEngine
    from app.strategies.sma import SMAStrategy

    monitor_cfg = settings.monitor
    engine = TradingEngine(
        risk_config=RiskConfig(**settings.risk.model_dump()),
        max_concurrent_orders=5,
        order_sync_interval=monitor_cfg.order_sync_interval_seconds,
        position_sync_interval=monitor_cfg.position_sync_interval_seconds,
        monitor_check_interval=monitor_cfg.check_interval_seconds,
        monitor_max_alerts=monitor_cfg.max_alerts,
    )

    # Trading exchanges require BOTH `enabled=true` AND a non-empty API key
    # AND global `enable_live_trading=true`. Public market data still works
    # via data sources registered in AppState, even when no trading
    # exchanges are present here.
    if settings.enable_live_trading:
        for name in ExchangeFactory.list_supported_exchanges():
            exchange_settings = settings.exchange(name)
            if exchange_settings is None or not exchange_settings.enabled:
                continue
            if not exchange_settings.api_key:
                # Data-source-only mode: skip trading registration.
                continue
            exchange = ExchangeFactory.get_or_create(
                name,
                api_key=exchange_settings.api_key,
                secret_key=exchange_settings.secret_key,
                passphrase=exchange_settings.passphrase,
                use_testnet=exchange_settings.use_testnet,
            )
            engine.add_exchange(name, exchange)

    engine.add_strategy("sma", SMAStrategy())
    return engine


async def run_trade(settings: Settings) -> None:
    """Run a minimal polling loop for the sample strategy.

    This is intentionally simple: fetch ticker -> feed strategy -> execute any
    actionable signal. Production trading should add persistence and dry-run
    accounting before real capital.
    """

    from loguru import logger

    engine = build_engine(settings)
    await engine.start()
    logger.info("Trading loop started for {} on {}", settings.default_exchange, settings.default_symbol)

    try:
        while True:
            # The engine stores exchanges by lower-case names such as "okx".
            exchange = engine._exchanges.get(settings.default_exchange.lower())
            if exchange is None:
                raise RuntimeError(f"Exchange is not configured: {settings.default_exchange}")

            # The SMA strategy consumes latest prices and only emits a signal
            # once enough history has accumulated.
            ticker = await exchange.get_ticker(settings.default_symbol)
            await engine.process_market_data(exchange.name, settings.default_symbol, ticker)
            await engine.check_and_execute_signals(exchange.name, settings.default_symbol)
            await asyncio.sleep(5)
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await engine.stop()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Web3 trading system")
    subparsers = parser.add_subparsers(dest="command", required=True)

    api_parser = subparsers.add_parser("api", help="Run FastAPI service")
    api_parser.add_argument("--host", default=None, help="API bind host")
    api_parser.add_argument("--port", type=int, default=None, help="API bind port")
    api_parser.add_argument("--workers", type=int, default=1, help="Uvicorn worker processes")

    subparsers.add_parser("trade", help="Run the sample strategy loop")
    subparsers.add_parser("status", help="Print configured exchanges")

    bot_parser = subparsers.add_parser(
        "bot", help="Run the Telegram monitor bot (long-polling)"
    )
    bot_parser.add_argument(
        "--engine-url",
        default=None,
        help="Engine API base URL (default: settings.bot.api_base_url or http://127.0.0.1:8000)",
    )

    return parser.parse_args(argv)


async def run_bot(settings: Settings, engine_url: str | None = None) -> None:
    """Start the Telegram bot monitoring loop.

    Wires the same ``TradingEngine`` instance the API is using as a target
    so the bot can call ``/api/v1/...`` over loopback. The bot itself can
    also be started independently (`python main.py bot`) — in that case it
    targets whatever URL ``--engine-url`` (or ``bot_api_base_url``) points
    to.
    """

    from loguru import logger

    from app.bot.alerts import BotAlertSubscriber
    from app.bot.config import bot_config_from_settings
    from app.bot.runner import TradingBot
    from app.bot.scheduler import autopilot_job, daily_report_job
    from app.bot.telegram import TelegramProvider

    cfg = bot_config_from_settings(settings)
    if engine_url:
        cfg = cfg.__class__(**{**cfg.__dict__, "api_base_url": engine_url})

    if not cfg.enabled:
        logger.warning(
            "Bot is disabled (settings.bot_enabled=false). "
            "Set BOT_ENABLED=true in .env to enable."
        )
        return
    if not cfg.telegram_token:
        logger.error("BOT_TELEGRAM_TOKEN is required but empty.")
        return

    provider = TelegramProvider(cfg)
    alert_subscriber = BotAlertSubscriber(config=cfg, sender=_push_all_text(cfg))
    bot = TradingBot(
        cfg,
        provider,
        monitor=None,  # bot 单独启时没有 engine.monitor；alert 推送禁用
        alert_subscriber=alert_subscriber,
        schedule_jobs=[
            *([daily_report_job] if cfg.daily_report_enabled else []),
            *([autopilot_job] if cfg.autopilot_enabled else []),
        ],
    )
    try:
        await bot.run_forever()
    except KeyboardInterrupt:
        logger.info("Bot received shutdown signal")


def _push_all_text(cfg):
    """返回一个 sender 闭包：直接给所有白名单 chat 推同一条消息。

    注意：bot.run_forever() 不在 main.py 里调用，所以这里只在用户希望
    "bot 单独跑"（不依赖 engine）的情况下成立。当 ``python main.py api``
    同时启 bot 时，这个工厂不需要。
    """

    async def sender(text: str) -> None:
        from loguru import logger

        logger.info(f"[bot-direct] {text}")

    return sender


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    settings = load_settings()
    try:
        # Logging depends on loguru. If dependencies are not installed yet,
        # keep basic commands usable instead of failing at import time.
        from app.core.logging import setup_logger

        setup_logger(settings.log_level)
    except ModuleNotFoundError:
        pass

    if args.command == "api":
        import uvicorn

        host = args.host or settings.host
        port = args.port or settings.port
        if args.workers > 1:
            # Multiple workers require an import string because uvicorn starts
            # separate processes and imports the app in each process.
            uvicorn.run(
                "app.api.server:create_app",
                factory=True,
                host=host,
                port=port,
                workers=args.workers,
            )
        else:
            # Single worker can reuse the already-loaded settings object.
            from app.api import create_app

            uvicorn.run(create_app(settings), host=host, port=port)
        return

    if args.command == "trade":
        asyncio.run(run_trade(settings))
        return

    if args.command == "bot":
        asyncio.run(run_bot(settings, engine_url=args.engine_url))
        return

    if args.command == "status":
        print(f"Supported exchanges: {ExchangeFactory.list_supported_exchanges()}")
        print(f"Default exchange: {settings.default_exchange}")
        print(f"Live trading enabled: {settings.enable_live_trading}")


if __name__ == "__main__":
    main()
