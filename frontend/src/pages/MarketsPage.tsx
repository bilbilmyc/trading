import { useEffect, useState, useCallback, useMemo } from "react";
import { useLocation } from "wouter";
import { TrendingUp } from "lucide-react";

import { useStatus } from "../contexts/StatusContext";
import { api } from "../api";
import type {
  ContractMarket,
  ExchangeName,
  FeeRate,
  OpenOrder,
  RecentTrade,
  Ticker,
} from "../api";
import { CandleChart, type Candle } from "../components/CandleChart";
import { EmptyState } from "../components/EmptyState";
import { KPIHero } from "../components/KPIHero";
import { PageHeader } from "../components/PageHeader";
import { Sparkline } from "../components/Sparkline";
import { formatNumber, formatPercent } from "../utils/format";

const EXCHANGES: { value: ExchangeName; label: string }[] = [
  { value: "binance_usdm", label: "Binance U 本位" },
  { value: "bitget_usdt_futures", label: "Bitget U 本位" },
  { value: "okx_swap", label: "OKX 永续" },
];

const INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;

export function MarketsPage() {
  const [location] = useLocation();
  const urlParams = new URLSearchParams(location.split("?")[1] || "");
  const { apiOnline } = useStatus();

  const [exchange, setExchange] = useState<ExchangeName>(
    (urlParams.get("source") as ExchangeName) || "binance_usdm",
  );
  const [symbol, setSymbol] = useState(urlParams.get("symbol") || "BTCUSDT");
  const [search, setSearch] = useState("");
  const [contracts, setContracts] = useState<ContractMarket[]>([]);
  const [interval, setInterval] = useState(
    () => localStorage.getItem("markets_interval") || "1h",
  );
  const [ticker, setTicker] = useState<Ticker | null>(null);
  const [trades, setTrades] = useState<RecentTrade[]>([]);
  const [openOrders, setOpenOrders] = useState<OpenOrder[]>([]);
  const [feeRate, setFeeRate] = useState<FeeRate | null>(null);
  const [candles, setCandles] = useState<Candle[]>([]);

  // ── data loaders ──────────────────────────────────────────────
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

  const refreshContracts = useCallback(async () => {
    if (!apiOnline) return;
    try {
      const r = await api.contracts(exchange, search, 200);
      setContracts(r.contracts);
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

  useEffect(() => { refreshKlines(); }, [refreshKlines]);
  useEffect(() => { refreshContracts(); }, [refreshContracts]);
  useEffect(() => { refreshMarket(); }, [refreshMarket]);
  useEffect(() => {
    if (!ticker || !apiOnline) return;
    const id = window.setInterval(refreshMarket, 3000);
    return () => window.clearInterval(id);
  }, [refreshMarket, ticker, apiOnline]);

  // ── derived ────────────────────────────────────────────────────
  const lastPrice = ticker?.last_price;
  const changePct = ticker?.price_change_pct_24h ?? 0;
  const changeAbs = ticker?.price_change_24h ?? 0;
  const isUp = changePct >= 0;

  // ticker-tape (top contracts, derive change vs last_price)
  const tape = useMemo(
    () => contracts.slice(0, 24).map((c) => ({ ...c })),
    [contracts],
  );

  return (
    <div className="page page--markets stack" style={{ paddingTop: 12 }}>
      <PageHeader
        icon={<TrendingUp size={18} />}
        eyebrow="合约行情"
        title="Markets"
        subtitle="K 线 / 深度 / 最近成交 / 24h 涨跌"
      />

      {/* KPI strip — top-of-page market summary. */}
      <div className="kpi-strip kpi-strip--four">
        <KPIHero
          label={`${symbol} 最新价`}
          value={lastPrice ? `$${formatNumber(lastPrice, 2)}` : "$--.--"}
          icon={<TrendingUp size={12} />}
          iconGradient={isUp ? "green" : "red"}
          delta={
            ticker
              ? {
                  value: `${isUp ? "+" : ""}${(changePct * 100).toFixed(2)}%`,
                  tone: isUp ? "positive" : "negative",
                }
              : undefined
          }
          sparkline={[10, 11, 12, 11, 13, 14, 13, 15, 14, 16, 15, 17]}
          hint="24h"
        />
        <KPIHero
          label="24h 成交额"
          value={ticker ? `$${(Number(ticker.quote_volume_24h) / 1e6).toFixed(1)}M` : "--"}
          icon={<TrendingUp size={12} />}
          iconGradient="cyan"
          sparkline={[8, 9, 8, 10, 11, 12, 11, 13, 12, 14, 13, 15]}
        />
        <KPIHero
          label="24h 最高 / 最低"
          value={
            ticker
              ? `$${formatNumber(ticker.high_24h, 2)} / $${formatNumber(ticker.low_24h, 2)}`
              : "--"
          }
          icon={<TrendingUp size={12} />}
          iconGradient="yellow"
        />
        <KPIHero
          label="买 / 卖价"
          value={
            ticker
              ? `$${formatNumber(ticker.bid_price, 2)} / $${formatNumber(ticker.ask_price, 2)}`
              : "--"
          }
          icon={<TrendingUp size={12} />}
          iconGradient="pink"
          hint="点差"
        />
      </div>

      {/* Filter row: compact, mono-style. */}
      <div className="form-grid form-grid--inline" style={{ gap: 8 }}>
        <label className="field">
          <span>EXCHANGE</span>
          <select
            value={exchange}
            onChange={(e) => setExchange(e.target.value as ExchangeName)}
          >
            {EXCHANGES.map((e) => (
              <option key={e.value} value={e.value}>{e.label}</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>SYMBOL</span>
          <input
            list="markets-symbol-list"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value.toUpperCase())}
            placeholder="BTCUSDT"
            style={{ fontFamily: "var(--font-mono)", letterSpacing: "0.04em" }}
          />
        </label>
        <label className="field">
          <span>INTERVAL</span>
          <select
            value={interval}
            onChange={(e) => {
              setInterval(e.target.value);
              localStorage.setItem("markets_interval", e.target.value);
            }}
          >
            {INTERVALS.map((i) => <option key={i} value={i}>{i}</option>)}
          </select>
        </label>
        <div className="field">
          <span>ACTION</span>
          <button type="button" className="action action--ghost" onClick={refreshMarket}>
            ↻ REFRESH
          </button>
        </div>
        <datalist id="markets-symbol-list">
          {contracts.slice(0, 200).map((c) => (
            <option key={`${c.exchange}-${c.symbol}`} value={c.symbol}>
              {c.base_asset} / {c.exchange}
            </option>
          ))}
        </datalist>
      </div>

      {/* Function-key style hint bar. */}
      <div className="fn-bar">
        <span><span className="fn-bar__key">F2</span> BID/ASK</span>
        <span><span className="fn-bar__key">F4</span> TRADES</span>
        <span><span className="fn-bar__key">F5</span> DEPTH</span>
        <span><span className="fn-bar__key">F6</span> ORDERS</span>
        <span style={{ marginLeft: "auto", color: "var(--text-faint)" }}>
          ⌘ CLICK a tape item to switch symbol
        </span>
      </div>

      {/* Hero price block — the "thesis" of the page. */}
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 16,
          padding: "12px 16px",
          background: "var(--bg-elevated)",
          border: "1px solid var(--border)",
          borderRadius: "var(--radius-md)",
          flexWrap: "wrap",
        }}
      >
        <span style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
          <TrendingUp size={16} className="text-muted" />
          <span className="data-mono data-mono--md" style={{ color: "var(--text-secondary)", fontWeight: 600 }}>
            {symbol}
          </span>
          <span className="data-mono data-mono--sm" style={{ color: "var(--text-muted)" }}>
            {interval.toUpperCase()} · {exchange.replace("_", " ")}
          </span>
        </span>
        <span className="big-price">
          {lastPrice ? `$${formatNumber(lastPrice, 2)}` : "$--.--"}
        </span>
        {ticker ? (
          <span className={`big-price__delta ${isUp ? "big-price__delta--pos" : "big-price__delta--neg"}`}>
            {isUp ? "▲" : "▼"} {isUp ? "+" : ""}
            {formatNumber(changeAbs, 2)} ({isUp ? "+" : ""}
            {formatNumber(changePct, 2)}%)
          </span>
        ) : null}
        <span style={{ marginLeft: "auto", display: "flex", gap: 8 }}>
          <span className="chip-sm">H ${formatNumber(ticker?.high_24h, 2)}</span>
          <span className="chip-sm">L ${formatNumber(ticker?.low_24h, 2)}</span>
          <span className="chip-sm">V ${formatNumber(ticker?.quote_volume_24h, 0)}</span>
        </span>
      </div>

      {/* Terminal: 3-column OKX-style layout. */}
      <div className="terminal">
        {/* LEFT: 最近成交 (order book / trades). */}
        <section
          style={{
            background: "var(--bg-elevated)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-md)",
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
          }}
        >
          <header
            style={{
              padding: "6px 10px",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              borderBottom: "1px solid var(--border)",
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              color: "var(--text-muted)",
            }}
          >
            <span>RECENT TRADES</span>
            <span>{trades.length}</span>
          </header>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "44px 1fr 1fr",
              padding: "4px 10px",
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--text-faint)",
              textTransform: "uppercase",
              letterSpacing: "0.06em",
              borderBottom: "1px solid var(--border)",
            }}
          >
            <span>Side</span><span style={{ textAlign: "right" }}>Price</span><span style={{ textAlign: "right" }}>Qty</span>
          </div>
          <div className="scroll-cap" style={{ flex: 1, minHeight: 0, maxHeight: 360 }}>
            {trades.length ? (
              trades.slice(0, 20).map((t) => {
                const up = t.side === "buy";
                return (
                  <div
                    key={t.trade_id}
                    className="tr"
                    style={{ gridTemplateColumns: "44px 1fr 1fr" }}
                  >
                    <span className={`tr__side ${up ? "tr__side--buy" : "tr__side--sell"}`}>
                      {up ? "买" : "卖"}
                    </span>
                    <span className={`tr__price ${up ? "tr__price--up" : "tr__price--down"}`} style={{ textAlign: "right" }}>
                      {formatNumber(t.price, 2)}
                    </span>
                    <span style={{ textAlign: "right" }}>{formatNumber(t.quantity, 4)}</span>
                  </div>
                );
              })
            ) : (
              <div className="empty-state" style={{ margin: 8 }}>
                <strong>暂无成交</strong>
                <span>选择合约后会自动开始流式拉取</span>
              </div>
            )}
          </div>
        </section>

        {/* CENTER: chart with structured empty state. */}
        <section
          style={{
            background: "var(--bg-elevated)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-md)",
            display: "flex",
            flexDirection: "column",
            overflow: "hidden",
          }}
        >
          <header
            style={{
              padding: "6px 10px",
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
              borderBottom: "1px solid var(--border)",
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              textTransform: "uppercase",
              letterSpacing: "0.08em",
              color: "var(--text-muted)",
            }}
          >
            <span>CANDLES · {symbol} · {interval}</span>
            <span style={{ display: "flex", gap: 6 }}>
              {INTERVALS.map((i) => (
                <button
                  key={i}
                  type="button"
                  className={`chip-sm ${i === interval ? "is-on" : ""}`}
                  onClick={() => {
                    setInterval(i);
                    localStorage.setItem("markets_interval", i);
                  }}
                >
                  {i}
                </button>
              ))}
            </span>
          </header>
          <div style={{ padding: 8, minHeight: 320 }}>
            {candles.length ? (
              <CandleChart candles={candles} />
            ) : (
              <div className="chart-empty">
                <span>暂无 K 线数据</span>
                <span className="chart-empty__hint">TIP · 等待 {symbol} 的首批 K 线回传 (3-5s)</span>
              </div>
            )}
          </div>
        </section>

        {/* RIGHT: 当前挂单 + 6 指标. */}
        <section
          style={{
            display: "flex",
            flexDirection: "column",
            gap: 12,
            minWidth: 0,
          }}
        >
          {/* 6 指标 grid */}
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr",
              gap: 6,
            }}
          >
            {[
              { label: "最新价", value: lastPrice ? `$${formatNumber(lastPrice, 2)}` : "$--", tone: "default" as const },
              { label: "24h 涨跌", value: `${isUp ? "+" : ""}${formatNumber(changePct, 2)}%`, tone: isUp ? "positive" as const : "negative" as const },
              { label: "24h 成交额", value: `$${formatNumber(ticker?.quote_volume_24h, 0)}`, tone: "muted" as const },
              { label: "Maker", value: formatPercent(feeRate?.maker), tone: "muted" as const },
              { label: "Taker", value: formatPercent(feeRate?.taker), tone: "muted" as const },
              { label: "买/卖价", value: `${formatNumber(ticker?.bid_price, 2)} / ${formatNumber(ticker?.ask_price, 2)}`, tone: "muted" as const },
            ].map((m) => (
              <div
                key={m.label}
                style={{
                  background: "var(--bg-card)",
                  border: "1px solid var(--border)",
                  borderRadius: "var(--radius-sm)",
                  padding: "8px 10px",
                }}
              >
                <div style={{ fontSize: 10, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--text-muted)", marginBottom: 2 }}>
                  {m.label}
                </div>
                <div
                  className="data-mono data-mono--md"
                  style={{
                    fontWeight: 600,
                    color: m.tone === "positive" ? "var(--positive)" : m.tone === "negative" ? "var(--negative)" : "var(--text-primary)",
                  }}
                >
                  {m.value}
                </div>
              </div>
            ))}
          </div>

          {/* 当前挂单 */}
          <section
            style={{
              background: "var(--bg-elevated)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-md)",
              display: "flex",
              flexDirection: "column",
              overflow: "hidden",
              flex: 1,
              minHeight: 0,
            }}
          >
            <header
              style={{
                padding: "6px 10px",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                borderBottom: "1px solid var(--border)",
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                textTransform: "uppercase",
                letterSpacing: "0.08em",
                color: "var(--text-muted)",
              }}
            >
              <span>OPEN ORDERS</span>
              <span>{openOrders.length}</span>
            </header>
            <div className="scroll-cap" style={{ flex: 1, minHeight: 0, maxHeight: 220 }}>
              {openOrders.length ? (
                openOrders.slice(0, 12).map((o, i) => (
                  <div key={String(o.order_id ?? o.orderId ?? i)} className="tr" style={{ gridTemplateColumns: "1fr 1fr 1fr" }}>
                    <span>{String(o.symbol ?? "--")}</span>
                    <span style={{ textAlign: "right" }}>${String(o.price ?? "--")}</span>
                    <span style={{ textAlign: "right", color: "var(--text-muted)" }}>
                      {String(o.status ?? o.quantity ?? "--")}
                    </span>
                  </div>
                ))
              ) : (
                <div className="empty-state" style={{ margin: 8 }}>
                  <strong>暂无挂单</strong>
                  <span>下单后会自动出现在此</span>
                </div>
              )}
            </div>
          </section>
        </section>
      </div>

      {/* Ticker tape: horizontal scrolling price strip (the "trader" affordance). */}
      <div className="ticker-tape" role="navigation" aria-label="热门合约">
        {tape.length === 0 ? (
          <span style={{ padding: "0 14px", color: "var(--text-faint)", fontFamily: "var(--font-mono)", fontSize: 11 }}>
            {apiOnline ? "加载合约..." : "等待 API..."}
          </span>
        ) : (
          tape.map((c) => (
            <button
              key={c.symbol}
              type="button"
              className="ticker-tape__item"
              onClick={() => setSymbol(c.symbol)}
              title={c.symbol}
              style={{ background: symbol === c.symbol ? "var(--accent-soft)" : "transparent" }}
            >
              <span className="ticker-tape__symbol">{c.base_asset}</span>
              <span className="ticker-tape__price">${formatNumber((c as any).last_price, 2) || "—"}</span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
