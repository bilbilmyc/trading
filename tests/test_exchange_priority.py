from app.exchanges.factory import ExchangeFactory
from config import Settings


def test_exchange_priority_and_defaults():
    supported = ExchangeFactory.list_supported_exchanges()

    assert supported[:3] == ["binance_usdm", "bitget_usdt_futures", "okx_swap"]

    settings = Settings()
    assert settings.default_exchange == "binance_usdm"
    assert settings.default_symbol == "BTCUSDT"
    assert settings.exchange("bitget_usdt_futures") is not None
    assert settings.exchange("bitget_usdt_futures").enabled is True
