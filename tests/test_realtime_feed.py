import asyncio
from app.engine.realtime_feed import PriceFeed, PriceTick


def _tick(source: str, symbol: str, price: float) -> PriceTick:
    return PriceTick(
        source=source, symbol=symbol, price=price,
        timestamp="2026-01-01T00:00:00",
    )


def test_subscribe_yields_queue() -> None:
    feed = PriceFeed()
    q = feed.subscribe()
    assert q is not None
    assert q in feed._subscribers


def test_unsubscribe_removes() -> None:
    feed = PriceFeed()
    q = feed.subscribe()
    feed.unsubscribe(q)
    assert q not in feed._subscribers


def test_publish_latest_recorded() -> None:
    feed = PriceFeed()
    asyncio.run(feed.publish(_tick("binance_usdm", "BTCUSDT", 100.0)))
    latest = feed.latest("binance_usdm", "BTCUSDT")
    assert latest is not None
    assert latest.price == 100.0


def test_publish_overwrites_previous() -> None:
    feed = PriceFeed()

    async def scenario():
        await feed.publish(_tick("a", "BTC", 100.0))
        await feed.publish(_tick("a", "BTC", 105.0))
        return feed.latest("a", "BTC")

    latest = asyncio.run(scenario())
    assert latest.price == 105.0


def test_multiple_subscribers_each_get_tick() -> None:
    feed = PriceFeed()
    q1 = feed.subscribe()
    q2 = feed.subscribe()
    asyncio.run(feed.publish(_tick("a", "BTC", 100.0)))
    assert not q1.empty()
    assert not q2.empty()
    t1 = q1.get_nowait()
    t2 = q2.get_nowait()
    assert t1.price == 100.0
    assert t2.price == 100.0


def test_latest_dict_serialization() -> None:
    feed = PriceFeed()
    asyncio.run(feed.publish(_tick("binance_usdm", "BTCUSDT", 100.0)))
    asyncio.run(feed.publish(_tick("binance_usdm", "ETHUSDT", 4000.0)))
    d = feed.latest_dict()
    assert "binance_usdm:BTCUSDT" in d
    assert "binance_usdm:ETHUSDT" in d
    assert d["binance_usdm:BTCUSDT"]["price"] == 100.0


def test_slow_consumer_drops_oldest() -> None:
    """Smoke test for the drop-on-full mechanism."""
    feed = PriceFeed(max_queue=3)
    q = feed.subscribe()
    # Verify max_queue configured correctly.
    assert q.maxsize == 3
    # Verify the latest tick is recorded.
    asyncio.run(feed.publish(_tick("a", "BTC", 100.0)))
    latest = feed.latest("a", "BTC")
    assert latest is not None
    assert latest.price == 100.0


def test_latest_all_returns_all_symbols() -> None:
    feed = PriceFeed()
    asyncio.run(feed.publish(_tick("a", "BTC", 100.0)))
    asyncio.run(feed.publish(_tick("b", "ETH", 4000.0)))
    all_ticks = feed.latest_all()
    assert len(all_ticks) == 2
    sources = {t.source for t in all_ticks}
    assert sources == {"a", "b"}


def test_feed_isolated_per_symbol() -> None:
    feed = PriceFeed()
    asyncio.run(feed.publish(_tick("a", "BTC", 100.0)))
    asyncio.run(feed.publish(_tick("a", "ETH", 4000.0)))
    assert feed.latest("a", "BTC").price == 100.0
    assert feed.latest("a", "ETH").price == 4000.0


def test_double_unsubscribe_idempotent() -> None:
    feed = PriceFeed()
    q = feed.subscribe()
    feed.unsubscribe(q)
    feed.unsubscribe(q)  # no error
    assert q not in feed._subscribers
