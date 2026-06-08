"""
Command entry point for the Web3 trading system.
"""

import argparse
import asyncio
from typing import Sequence

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

    for name in ExchangeFactory.list_supported_exchanges():
        exchange_settings = settings.exchange(name)
        if exchange_settings is None or not exchange_settings.enabled:
            continue

        # One adapter instance owns its HTTP client and WebSocket tasks.
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

    return parser.parse_args(argv)


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

    if args.command == "status":
        print(f"Supported exchanges: {ExchangeFactory.list_supported_exchanges()}")
        print(f"Default exchange: {settings.default_exchange}")
        print(f"Live trading enabled: {settings.enable_live_trading}")


if __name__ == "__main__":
    main()
