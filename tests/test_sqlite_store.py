from app.core.sqlite_store import SQLiteStore


def test_sqlite_store_persists_strategy_signal_and_paper_state(tmp_path):
    store = SQLiteStore(str(tmp_path / "trading.sqlite3"))

    store.upsert_strategy(
        {
            "name": "sma_test",
            "class_name": "SMAStrategy",
            "exchange": "binance_usdm",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "running": True,
            "mode": "paper",
            "initialized_at": "2026-06-09T00:00:00",
            "updated_at": "2026-06-09T00:00:01",
            "parameters": {"short_window": 5, "long_window": 20, "min_data_points": 20},
        }
    )

    assert store.list_strategies() == [
        {
            "name": "sma_test",
            "class_name": "SMAStrategy",
            "exchange": "binance_usdm",
            "symbol": "BTCUSDT",
            "interval": "1m",
            "enabled": True,
            "mode": "paper",
            "initialized_at": "2026-06-09T00:00:00",
            "updated_at": "2026-06-09T00:00:01",
            "parameters": {"long_window": 20, "min_data_points": 20, "short_window": 5},
        }
    ]

    signal = {
        "exchange": "binance_usdm",
        "strategy": "sma_test",
        "symbol": "BTCUSDT",
        "action": "buy",
        "strength": 1.0,
        "quantity": 0.001,
        "price": 62500.0,
        "order_type": "market",
        "stop_loss": None,
        "take_profit": None,
        "metadata": {"crossover_type": "golden"},
        "actionable": True,
        "timestamp": "2026-06-09T00:00:02",
    }
    store.append_signal(signal)
    assert store.recent_signals(limit=1) == [signal]

    order = {
        "order_id": "paper_1",
        "exchange": "binance_usdm",
        "strategy": "sma_test",
        "symbol": "BTCUSDT",
        "side": "buy",
        "quantity": 0.001,
        "price": 62500.0,
        "fee": 0.03125,
        "realized_pnl": 0.0,
        "status": "filled",
        "timestamp": "2026-06-09T00:00:03",
        "signal_metadata": {"crossover_type": "golden"},
    }
    store.save_paper_order(order)
    store.save_paper_state(
        {
            "enabled": True,
            "initial_cash": 10000.0,
            "cash": 9999.96875,
            "fee_rate": 0.0005,
            "positions": [
                {
                    "exchange": "binance_usdm",
                    "symbol": "BTCUSDT",
                    "quantity": 0.001,
                    "avg_entry_price": 62500.0,
                    "current_price": 62600.0,
                    "realized_pnl": 0.0,
                    "unrealized_pnl": 0.1,
                    "updated_at": "2026-06-09T00:00:04",
                }
            ],
        }
    )

    state = store.load_paper_state()
    assert state["account"]["cash"] == 9999.96875
    assert state["positions"][0]["symbol"] == "BTCUSDT"
    assert state["orders"] == [order]

    store.delete_strategy("sma_test")
    assert store.list_strategies() == []
    store.close()
