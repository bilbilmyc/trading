"""
Application settings.

Environment variables are loaded from .env when present. Keep credentials out of
source control and prefer testnet/simulated trading until the whole flow has
been verified.
"""

import os
from functools import lru_cache

from pydantic import BaseModel, Field

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    # 这个 fallback 只用于“依赖还没装全，但想先跑 status/基础导入”的场景。
    # 正常运行时 requirements.txt 会安装 pydantic-settings，并走上面的官方实现。
    SettingsConfigDict = dict

    def _read_dotenv(path: str = ".env") -> dict[str, str]:
        """Read simple KEY=value lines from .env without pulling extra dependencies."""

        values: dict[str, str] = {}
        if not os.path.exists(path):
            return values
        with open(path, encoding="utf-8") as env_file:
            for line in env_file:
                stripped = line.strip()
                if not stripped or stripped.startswith("#") or "=" not in stripped:
                    continue
                key, value = stripped.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
        return values

    class BaseSettings(BaseModel):
        """Small fallback when pydantic-settings is not installed."""

        def __init__(self, **values):
            env_values = _read_dotenv()
            for field_name in type(self).model_fields:
                env_name = field_name.upper()
                # Environment variables have higher priority than .env values.
                if env_name in os.environ:
                    env_values[env_name] = os.environ[env_name]
                if env_name in env_values and field_name not in values:
                    values[field_name] = env_values[env_name]
            super().__init__(**values)


class ExchangeSettings(BaseModel):
    """Credentials and runtime options for one exchange."""

    api_key: str = ""
    secret_key: str = ""
    passphrase: str = ""
    use_testnet: bool = True
    enabled: bool = False


class RiskSettings(BaseModel):
    """Risk limits used by the trading engine."""

    max_position_size: float = 1.0
    max_position_value: float = 1000.0
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.10
    max_daily_loss: float = 100.0
    max_drawdown_pct: float = 0.20
    max_orders_per_minute: int = 5


class MonitorSettings(BaseModel):
    """Alert threshold and scheduling settings."""

    check_interval_seconds: int = 30
    max_alerts: int = 100
    order_sync_interval_seconds: int = 10
    position_sync_interval_seconds: int = 15


class LLMSettings(BaseModel):
    """LLM / AI analysis settings."""

    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    temperature: float = 0.3
    max_tokens: int = 2048
    request_timeout: float = 30.0
    min_candles: int = 20
    max_candles: int = 100
    default_order_amount: float = 50.0  # USDT, 单笔默认金额


class BotSettings(BaseModel):
    """Telegram bot 监控盯盘的运行时配置。

    默认值与旧版 getattr 默认值一致，保证向后兼容；启用需要显式
    设置 ``bot_enabled=true`` 并提供 ``bot_telegram_token``。
    """

    enabled: bool = False
    telegram_token: str = ""
    allowed_chat_ids: tuple[int, ...] = ()
    api_base_url: str = "http://127.0.0.1:8000"
    api_key: str = ""
    request_timeout_seconds: float = 10.0
    event_poll_interval_seconds: float = 5.0
    daily_report_enabled: bool = True
    daily_report_hour: int = 0
    daily_report_minute: int = 5
    quiet_hours: tuple[int, int] | None = None
    send_rate_per_second: float = 4.0
    # Proactive alert forwarding from the monitor.
    min_alert_level: str = "warning"  # info | warning | error | critical
    alert_fingerprint_cooldown_seconds: int = 300
    # Scope tag for outgoing API calls (recorded by the server in access logs).
    outbound_scope: str = "monitor"


class Settings(BaseSettings):
    """Top-level application settings."""

    # Application/runtime settings.
    app_name: str = "Web3 Trading System"
    app_env: str = "development"
    log_level: str = "INFO"

    host: str = "0.0.0.0"
    port: int = 8000
    frontend_static_dir: str = "static"
    sqlite_path: str = "data/trading.sqlite3"
    market_data_catalog_path: str = "data/market_data.duckdb"
    market_data_parquet_dir: str = "data/market_data"

    default_exchange: str = "binance_usdm"
    default_symbol: str = "BTCUSDT"
    enable_live_trading: bool = False

    # Exchange credentials are split into flat env vars so .env remains simple:
    # OKX_API_KEY=..., BINANCE_SECRET_KEY=..., etc.
    okx_api_key: str = ""
    okx_secret_key: str = ""
    okx_passphrase: str = ""
    okx_use_testnet: bool = True
    okx_enabled: bool = True
    okx_swap_enabled: bool = True

    binance_api_key: str = ""
    binance_secret_key: str = ""
    binance_use_testnet: bool = True
    binance_enabled: bool = True
    binance_usdm_enabled: bool = True

    bitget_api_key: str = ""
    bitget_secret_key: str = ""
    bitget_passphrase: str = ""
    bitget_use_testnet: bool = True
    bitget_enabled: bool = True
    bitget_usdt_futures_enabled: bool = True

    # Risk defaults are conservative. Increase them only after dry-run testing.
    max_position_size: float = Field(default=1.0, gt=0)
    max_position_value: float = Field(default=1000.0, gt=0)
    stop_loss_pct: float = Field(default=0.05, gt=0, le=1)
    take_profit_pct: float = Field(default=0.10, gt=0)
    max_daily_loss: float = Field(default=100.0, gt=0)
    max_drawdown_pct: float = Field(default=0.20, gt=0, le=1)
    max_orders_per_minute: int = Field(default=5, gt=0)

    # Monitor / sync intervals
    order_sync_interval_seconds: int = 10
    position_sync_interval_seconds: int = 15
    monitor_check_interval_seconds: int = 30
    monitor_max_alerts: int = 100

    # LLM / AI analysis
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_temperature: float = 0.3
    llm_max_tokens: int = 2048
    llm_request_timeout: float = 30.0
    # Strategy-scoped LLM availability controls. Cache hits bypass these
    # limits; defaults preserve the existing request cadence.
    llm_min_request_interval_seconds: float = Field(default=0.0, ge=0, le=3600)
    llm_circuit_failure_threshold: int = Field(default=3, ge=1, le=100)
    llm_circuit_cooldown_seconds: float = Field(default=60.0, ge=1, le=3600)
    llm_min_candles: int = 20
    llm_max_candles: int = 100
    llm_default_order_amount: float = 50.0

    # Optional API auth. Empty (default) = no check; set AUTH_API_KEY=... in
    # .env to require `Authorization: Bearer <key>` on dangerous endpoints.
    # Local personal use can keep this empty; expose to a network and you
    # should set it.
    auth_api_key: str = ""

    # Alert dispatch. Each URL is a custom-bot webhook. Empty = provider
    # disabled. min_level filters which alerts are forwarded (info/warning/
    # error/critical). See docs/alerts.md for setup instructions.
    alert_min_level: str = "warning"
    alert_feishu_webhook: str = ""
    alert_dingtalk_webhook: str = ""
    alert_wecom_webhook: str = ""
    alert_http_timeout: float = 10.0

    # Symbol whitelist for LLM-driven strategies. Empty (default) = the
    # LLM may decide on any symbol it sees. Set to a JSON list in .env
    # to restrict to explicit symbols, e.g.:
    #   LLM_ALLOWED_SYMBOLS=["BTCUSDT","ETHUSDT","SOLUSDT"]
    llm_allowed_symbols: list = []

    # Bot 监控盯盘 (Telegram). All fields are disabled-by-default. To
    # enable, set BOT_ENABLED=true and provide BOT_TELEGRAM_TOKEN. See
    # docs/bot.md for the full command list and webhook setup.
    bot_enabled: bool = False
    bot_telegram_token: str = ""
    bot_allowed_chat_ids: str = ""            # CSV, e.g. "-1001234567890,123456789"
    bot_api_base_url: str = "http://127.0.0.1:8000"
    bot_api_key: str = ""                     # empty -> 降级到 auth_api_key
    bot_request_timeout_seconds: float = 10.0
    bot_event_poll_interval_seconds: float = 5.0
    bot_daily_report_enabled: bool = True
    bot_daily_report_hour: int = 0
    bot_daily_report_minute: int = 5
    bot_quiet_hours: str = ""                  # "22-8" 闭区间
    bot_send_rate_per_second: float = 4.0
    bot_min_alert_level: str = "warning"
    bot_alert_fingerprint_cooldown_seconds: int = 300
    bot_outbound_scope: str = "monitor"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def okx(self) -> ExchangeSettings:
        """Group flat OKX environment variables into one exchange settings object."""

        return ExchangeSettings(
            api_key=self.okx_api_key,
            secret_key=self.okx_secret_key,
            passphrase=self.okx_passphrase,
            use_testnet=self.okx_use_testnet,
            enabled=self.okx_enabled,
        )

    @property
    def binance(self) -> ExchangeSettings:
        """Group flat Binance environment variables into one exchange settings object."""

        return ExchangeSettings(
            api_key=self.binance_api_key,
            secret_key=self.binance_secret_key,
            use_testnet=self.binance_use_testnet,
            enabled=self.binance_enabled,
        )

    @property
    def bitget(self) -> ExchangeSettings:
        """Group flat Bitget environment variables into one exchange settings object."""

        return ExchangeSettings(
            api_key=self.bitget_api_key,
            secret_key=self.bitget_secret_key,
            passphrase=self.bitget_passphrase,
            use_testnet=self.bitget_use_testnet,
            enabled=self.bitget_enabled,
        )

    @property
    def llm(self) -> LLMSettings:
        """Build LLMSettings from flat env fields."""

        return LLMSettings(
            api_key=self.llm_api_key,
            base_url=self.llm_base_url,
            model=self.llm_model,
            temperature=self.llm_temperature,
            max_tokens=self.llm_max_tokens,
            request_timeout=self.llm_request_timeout,
            min_candles=self.llm_min_candles,
            max_candles=self.llm_max_candles,
            default_order_amount=self.llm_default_order_amount,
        )

    @property
    def monitor(self) -> MonitorSettings:
        """Build the MonitorSettings from flat env fields."""

        return MonitorSettings(
            check_interval_seconds=self.monitor_check_interval_seconds,
            max_alerts=self.monitor_max_alerts,
            order_sync_interval_seconds=self.order_sync_interval_seconds,
            position_sync_interval_seconds=self.position_sync_interval_seconds,
        )

    @property
    def bot(self) -> BotSettings:
        """把扁平的 bot_* 环境变量聚合到 BotSettings。"""

        raw = (self.bot_allowed_chat_ids or "").strip()
        chat_ids: tuple[int, ...] = tuple(
            int(p)
            for p in (s.strip() for s in raw.split(","))
            if p and p.lstrip("-").isdigit()
        )
        quiet: tuple[int, int] | None = None
        quiet_raw = (self.bot_quiet_hours or "").strip()
        if quiet_raw:
            try:
                start, end = (x.strip() for x in quiet_raw.split("-", 1))
                quiet = (int(start), int(end))
            except (ValueError, AttributeError):
                quiet = None
        return BotSettings(
            enabled=self.bot_enabled,
            telegram_token=self.bot_telegram_token,
            allowed_chat_ids=chat_ids,
            api_base_url=self.bot_api_base_url,
            api_key=self.bot_api_key or self.auth_api_key,
            request_timeout_seconds=self.bot_request_timeout_seconds,
            event_poll_interval_seconds=self.bot_event_poll_interval_seconds,
            daily_report_enabled=self.bot_daily_report_enabled,
            daily_report_hour=self.bot_daily_report_hour,
            daily_report_minute=self.bot_daily_report_minute,
            quiet_hours=quiet,
            send_rate_per_second=self.bot_send_rate_per_second,
            min_alert_level=self.bot_min_alert_level,
            alert_fingerprint_cooldown_seconds=self.bot_alert_fingerprint_cooldown_seconds,
            outbound_scope=self.bot_outbound_scope,
        )

    @property
    def risk(self) -> RiskSettings:
        """Build the RiskConfig-compatible settings used by the trading engine."""

        return RiskSettings(
            max_position_size=self.max_position_size,
            max_position_value=self.max_position_value,
            stop_loss_pct=self.stop_loss_pct,
            take_profit_pct=self.take_profit_pct,
            max_daily_loss=self.max_daily_loss,
            max_drawdown_pct=self.max_drawdown_pct,
            max_orders_per_minute=self.max_orders_per_minute,
        )

    def exchange(self, name: str) -> ExchangeSettings | None:
        """Return settings for an exchange by its public name."""

        exchanges = {
            "okx": self.okx,
            "binance": self.binance,
            "bitget": self.bitget,
            "okx_swap": self.okx.model_copy(update={"enabled": self.okx_swap_enabled}),
            "binance_usdm": self.binance.model_copy(update={"enabled": self.binance_usdm_enabled}),
            "bitget_usdt_futures": self.bitget.model_copy(update={"enabled": self.bitget_usdt_futures_enabled}),
        }
        return exchanges.get(name.lower())


@lru_cache
def load_settings() -> Settings:
    """Load settings once per process."""

    return Settings()
