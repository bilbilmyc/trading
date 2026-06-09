"""
Application settings.

Environment variables are loaded from .env when present. Keep credentials out of
source control and prefer testnet/simulated trading until the whole flow has
been verified.
"""

from functools import lru_cache
import os
from typing import Optional

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
        with open(path, "r", encoding="utf-8") as env_file:
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
    llm_min_candles: int = 20
    llm_max_candles: int = 100
    llm_default_order_amount: float = 50.0

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

    def exchange(self, name: str) -> Optional[ExchangeSettings]:
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
