import { useEffect, useState, useCallback } from "react";
import { useLocation } from "wouter";
import { useStatus } from "../contexts/StatusContext";
import { api } from "../api";
import type {
  ContractMarket,
  CostEstimate,
  ExchangeName,
  FeeRate,
  Liquidity,
  OpenOrder,
  RecentTrade,
  Ticker,
} from "../api";
import { CandleChart, type Candle } from "../components/CandleChart";
import { EmptyState, Metric, SectionTitle } from "../components/atoms";

function formatNumber(value: number | undefined, digits = 4): string {
  if (value === undefined || Number.isNaN(value)) return "--";
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: digits, minimumFractionDigits: 0 }).format(value);
}

function formatPercent(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return "--";
  return `${(value * 100).toFixed(4)}%`;
}

export function MarketsPage() {
  const [location] = useLocation();
  const urlParams = new URLSearchParams(location.split("?")[1] || "");
  const { apiOnline } = useStatus();
  const [exchange, setExchange] = useState<ExchangeName>(() => {
    const q = (urlParams.get("source") as ExchangeName) || "binance_usdm";
    return q;
  });
  const [symbol, setSymbol] = useState(() => urlParams.get("symbol") || "BTCUSDT");
  const [search, setSearch] = useState("");
  const [contracts, setContracts] = useState<ContractMarket[]>([]);
  const [interval, setInterval] = useState(() => {
    const saved = localStorage.getItem("markets_interval");
    return saved || "1h";
  });
  const [ticker, setTicker] = useState<Ticker | null>(null);
  const [trades, setTrades] = useState<RecentTrade[]>([]);
  const [openOrders, setOpenOrders] = useState<OpenOrder[]>([]);
  const [feeRate, setFeeRate] = useState<FeeRate | null>(null);
  const [estimate, setEstimate] = useState<CostEstimate | null>(null);
  const [liquidity, setLiquidity] = useState<Liquidity>("maker");
  const [candles, setCandles] = useState<Candle[]>([]);

  const refreshKlines = useCallback(async () => {
    if (!apiOnline || !symbol) return;
    try {
      const klines = await api.klines(exchange, symbol, interval, 80);
      setCandles(
        klines.map((k: any) => ({
          open_time: k.open_time ?? k.openTime ?? 0,
          open: Number(k.open ?? 0),
          high: Number(k.high ?? 0),
          low: Number(k.low ?? 0),
          close: Number(k.close ?? 0),
          volume: k.volume != null ? Number(k.volume) : undefined,
        })),
      );
    } catch {
      setCandles([]);
    }
  }, [apiOnline, exchange, symbol, interval]);

  useEffect(() => { refreshKlines(); }, [refreshKlines]);

  const refreshContracts = useCallback(async () => {
    if (!apiOnline) return;
    try {
      const result = await api.contracts(exchange, search, 200);
      setContracts(result.contracts);
    } catch {
      setContracts([]);
    }
  }, [apiOnline, exchange, search]);

  const refreshMarket = useCallback(async () => {
    if (!apiOnline || !symbol) return;
    try {
      const [t, ts, oo, fr] = await Promise.all([
        api.ticker(exchange, symbol),
        api.recentTrades(exchange, symbol),
        api.openOrders(exchange, symbol),
        api.feeRate(exchange, symbol),
      ]);
      setTicker(t);
      setTrades(ts);
      setOpenOrders(oo);
      setFeeRate(fr);
    } catch {
      /* keep last */
    }
  }, [apiOnline, exchange, symbol]);

  useEffect(() => { refreshContracts(); }, [refreshContracts]);
  useEffect(() => { refreshMarket(); }, [refreshMarket]);
  useEffect(() => {
    if (!ticker || !apiOnline || !symbol) return;
    const id = window.setInterval(refreshMarket, 3000);
    return () => window.clearInterval(id);
  }, [refreshMarket, ticker, apiOnline, symbol]);

  return (
    <div className="page page--markets">
      <header className="page__header">
        <div>
          <p className="eyebrow">行情监控</p>
          <h1>Markets</h1>
          <span className="page__subtitle">Ticker · 成交 · 挂单 · 费率 · 成本估算 · 3s 刷新</span>
        </div>
      </header>

      <div className="form-grid form-grid--inline">
        <label className="field">
          <span>交易所</span>
          <select value={exchange} onChange={(e) => setExchange(e.target.value as ExchangeName)}>
            <option value="binance_usdm">Binance U 本位</option>
            <option value="bitget_usdt_futures">Bitget U 本位</option>
            <option value="okx_swap">OKX 永续</option>
          </select>
        </label>
        <label className="field">
          <span>合约代码</span>
          <input value={symbol} onChange={(e) => setSymbol(e.target.value)} />
        </label>
        <label className="field">
          <span>搜索</span>
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="BTC, ETH..." />
        </label>
        <div className="field">
          <button className="action action--ghost" onClick={refreshMarket}>
            刷新
          </button>
        </div>
      </div>

      <div className="form-grid form-grid--inline">
        <label className="field">
          <span>周期</span>
          <select
            value={interval}
            onChange={(e) => {
              setInterval(e.target.value);
              localStorage.setItem("markets_interval", e.target.value);
            }}
          >
            <option value="1m">1m</option>
            <option value="5m">5m</option>
            <option value="15m">15m</option>
            <option value="1h">1h</option>
            <option value="4h">4h</option>
            <option value="1d">1d</option>
          </select>
        </label>
      </div>

      <SectionTitle title={`${symbol} K 线`} subtitle={`${interval} · 最近 80 根`} />
      <CandleChart candles={candles} />

      <div className="metric-grid">
        <Metric label="最新价" value={`$${formatNumber(ticker?.last_price, 2)}`} />
        <Metric label="24h 涨跌" value={`${formatNumber(ticker?.price_change_pct_24h, 2)}%`} tone={(ticker?.price_change_pct_24h ?? 0) >= 0 ? "positive" : "negative"} />
        <Metric label="24h 成交额" value={`$${formatNumber(ticker?.quote_volume_24h, 0)}`} tone="muted" />
        <Metric label="Maker" value={formatPercent(feeRate?.maker)} tone="muted" />
        <Metric label="Taker" value={formatPercent(feeRate?.taker)} tone="muted" />
      </div>

      <div className="market-picker">
        {contracts.slice(0, 12).map((c) => (
          <button
            key={c.symbol}
            className={`market-picker__chip ${symbol === c.symbol ? "active" : ""}`}
            onClick={() => setSymbol(c.symbol)}
            type="button"
          >
            <strong>{c.base_asset}</strong>
            <small>{c.symbol}</small>
          </button>
        ))}
      </div>

      <div className="page__grid page__grid--two-thirds">
        <section className="panel">
          <SectionTitle title="最近成交" subtitle={`${trades.length} 条`} />
          <div className="trade-list">
            {trades.length ? (
              trades.slice(0, 20).map((t) => (
                <div className="trade-row" key={t.trade_id}>
                  <span className={`tag ${t.side === "buy" ? "tag--buy" : "tag--sell"}`}>
                    {t.side === "buy" ? "买" : "卖"}
                  </span>
                  <strong>${formatNumber(t.price, 2)}</strong>
                  <small>{formatNumber(t.quantity, 6)}</small>
                </div>
              ))
            ) : (
              <EmptyState>暂无成交</EmptyState>
            )}
          </div>
        </section>

        <section className="panel">
          <SectionTitle title="当前挂单" subtitle={`${openOrders.length} 个`} />
          <div className="trade-list">
            {openOrders.length ? (
              openOrders.slice(0, 12).map((o, i) => (
                <div className="trade-row" key={String(o.order_id ?? o.orderId ?? i)}>
                  <span className="tag tag--neutral">{String(o.side ?? "--")}</span>
                  <strong>${String(o.price ?? "--")}</strong>
                  <small>{String(o.status ?? o.quantity ?? "--")}</small>
                </div>
              ))
            ) : (
              <EmptyState>暂无挂单</EmptyState>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}