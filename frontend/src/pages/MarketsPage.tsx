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
import { MarketSnapshot } from "../components/MarketSnapshot";
import { PageHeader } from "../components/PageHeader";
import { SectionPanel } from "../components/SectionPanel";
import { formatNumber, formatPercent } from "../utils/format";

const EXCHANGES: { value: ExchangeName; label: string }[] = [
  { value: "binance_usdm", label: "Binance U 本位" },
  { value: "bitget_usdt_futures", label: "Bitget U 本位" },
  { value: "okx_swap", label: "OKX 永续" },
];

const INTERVALS = ["1m", "5m", "15m", "1h", "4h", "1d"] as const;

type MiniTone = "pos" | "neg" | "muted";

interface MiniMetric {
  label: string;
  value: string;
  tone?: MiniTone;
}

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
  const priceChangePct = ticker?.price_change_pct_24h ?? 0;

  // ticker-tape (top contracts, derive change vs last_price)
  const tape = useMemo(
    () => contracts.slice(0, 24).map((c) => ({ ...c })),
    [contracts],
  );

  const miniMetrics: MiniMetric[] = [
    {
      label: "最新价",
      value: lastPrice ? `$${formatNumber(lastPrice, 2)}` : "—",
      tone: "muted",
    },
    {
      label: "24h 涨跌",
      value: `${isUp ? "+" : ""}${formatNumber(changePct, 2)}%`,
      tone: isUp ? "pos" : "neg",
    },
    {
      label: "24h 成交额",
      value: `$${formatNumber(ticker?.quote_volume_24h, 0)}`,
      tone: "muted",
    },
    { label: "Maker", value: formatPercent(feeRate?.maker), tone: "muted" },
    { label: "Taker", value: formatPercent(feeRate?.taker), tone: "muted" },
    {
      label: "买/卖价",
      value: `${formatNumber(ticker?.bid_price, 2)} / ${formatNumber(ticker?.ask_price, 2)}`,
      tone: "muted",
    },
  ];

  return (
    <div className="page page--markets stack">
      <PageHeader
        icon={<TrendingUp size={18} />}
        eyebrow="合约行情"
        title="Markets"
        subtitle="K 线 / 深度 / 最近成交 / 24h 涨跌"
      />

      {/* v0.4 stats strip — hairline tiles, tabular figures. */}
      <div className="market-snap-strip">
        <MarketSnapshot
          label={`${symbol} 最新价`}
          value={lastPrice ? `$${formatNumber(lastPrice, 2)}` : "$—"}
          icon={<TrendingUp size={12} />}
          delta={
            ticker
              ? {
                  value: `${isUp ? "+" : ""}${(priceChangePct * 100).toFixed(2)}%`,
                  tone: isUp ? "positive" : "negative",
                }
              : undefined
          }
          sparkline={[10, 11, 12, 11, 13, 14, 13, 15, 14, 16, 15, 17]}
          hint="24h"
        />
        <MarketSnapshot
          label="24h 成交额"
          value={ticker ? `$${(Number(ticker.quote_volume_24h) / 1e6).toFixed(1)}M` : "—"}
          icon={<TrendingUp size={12} />}
          sparkline={[8, 9, 8, 10, 11, 12, 11, 13, 12, 14, 13, 15]}
        />
        <MarketSnapshot
          label="24h 最高 / 最低"
          value={
            ticker
              ? `$${formatNumber(ticker.high_24h, 2)} / $${formatNumber(ticker.low_24h, 2)}`
              : "—"
          }
          icon={<TrendingUp size={12} />}
        />
        <MarketSnapshot
          label="买 / 卖价"
          value={
            ticker
              ? `$${formatNumber(ticker.bid_price, 2)} / $${formatNumber(ticker.ask_price, 2)}`
              : "—"
          }
          icon={<TrendingUp size={12} />}
          hint="点差"
        />
      </div>

      {/* Filter row: compact, mono-style. */}
      <div className="form-grid form-grid--inline markets-filter-row">
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
            className="num markets-symbol-input"
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

      <div className="fn-bar">
        <span><span className="fn-bar__key">F2</span> BID/ASK</span>
        <span><span className="fn-bar__key">F4</span> TRADES</span>
        <span><span className="fn-bar__key">F5</span> DEPTH</span>
        <span><span className="fn-bar__key">F6</span> ORDERS</span>
        <span className="fn-bar__hint">
          ⌘ CLICK a tape item to switch symbol
        </span>
      </div>

      {/* Hero price block — the "thesis" of the page. */}
      <div className="markets-hero">
        <span className="markets-hero__symbol-cluster">
          <TrendingUp size={16} className="text-muted markets-hero__icon" />
          <span className="markets-hero__symbol num">{symbol}</span>
          <span className="markets-hero__meta num">
            {interval.toUpperCase()} · {exchange.replace("_", " ")}
          </span>
        </span>
        <span className="markets-hero__price num">
          {lastPrice ? `$${formatNumber(lastPrice, 2)}` : "$—"}
        </span>
        {ticker ? (
          <span
            className={`markets-hero__delta ${isUp ? "markets-hero__delta--pos" : "markets-hero__delta--neg"} num`}
          >
            {isUp ? "▲" : "▼"} {isUp ? "+" : ""}
            {formatNumber(changeAbs, 2)} ({isUp ? "+" : ""}
            {formatNumber(changePct, 2)}%)
          </span>
        ) : null}
        <span className="markets-hero__chips">
          <span className="markets-hero__chip">H ${formatNumber(ticker?.high_24h, 2)}</span>
          <span className="markets-hero__chip">L ${formatNumber(ticker?.low_24h, 2)}</span>
          <span className="markets-hero__chip">V ${formatNumber(ticker?.quote_volume_24h, 0)}</span>
        </span>
      </div>

      {/* 3-column terminal layout: trades / candles / open orders. */}
      <div className="terminal-grid-markets">
        <SectionPanel
          title={`RECENT TRADES · ${symbol}`}
          trailing={<span>{trades.length}</span>}
          scroll="md"
        >
          <div className="tr" style={{ gridTemplateColumns: "44px 1fr 1fr" }}>
            <span>Side</span>
            <span className="tr__head-num">Price</span>
            <span className="tr__head-num">Qty</span>
          </div>
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
                  <span className={`tr__price ${up ? "tr__price--up" : "tr__price--down"} num`}>
                    {formatNumber(t.price, 2)}
                  </span>
                  <span className="tr__qty num">{formatNumber(t.quantity, 4)}</span>
                </div>
              );
            })
          ) : (
            <div className="empty-state empty-state--compact">
              <strong>暂无成交</strong>
              <span>选择合约后会自动开始流式拉取</span>
            </div>
          )}
        </SectionPanel>

        <SectionPanel
          title={
            <span>
              CANDLES · <span className="num">{symbol}</span> · <span className="num">{interval}</span>
            </span>
          }
          trailing={
            <span className="section-panel__trailing">
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
          }
        >
          <div className="markets-candle-host">
            {candles.length ? (
              <CandleChart candles={candles} />
            ) : (
              <div className="chart-empty">
                <span>暂无 K 线数据</span>
                <span className="chart-empty__hint">
                  TIP · 等待 {symbol} 的首批 K 线回传 (3-5s)
                </span>
              </div>
            )}
          </div>
        </SectionPanel>

        <div className="markets-right-col">
          <div className="markets-mini-grid">
            {miniMetrics.map((m) => (
              <div key={m.label} className="markets-mini">
                <div className="markets-mini__label">{m.label}</div>
                <div
                  className={`markets-mini__value num ${
                    m.tone === "pos"
                      ? "markets-mini__value--pos"
                      : m.tone === "neg"
                        ? "markets-mini__value--neg"
                        : "markets-mini__value--muted"
                  }`}
                >
                  {m.value}
                </div>
              </div>
            ))}
          </div>

          <SectionPanel
            title={`OPEN ORDERS · ${symbol}`}
            trailing={<span>{openOrders.length}</span>}
            flex
            scroll="sm"
          >
            {openOrders.length ? (
              openOrders.slice(0, 12).map((o, i) => (
                <div
                  key={String(o.order_id ?? o.orderId ?? i)}
                  className="tr"
                  style={{ gridTemplateColumns: "1fr 1fr 1fr" }}
                >
                  <span className="num">{String(o.symbol ?? "—")}</span>
                  <span className="num tr__price--up" style={{ textAlign: "right" }}>
                    ${String(o.price ?? "—")}
                  </span>
                  <span className="num" style={{ textAlign: "right", color: "var(--text-muted)" }}>
                    {String(o.status ?? o.quantity ?? "—")}
                  </span>
                </div>
              ))
            ) : (
              <div className="empty-state empty-state--compact">
                <strong>暂无挂单</strong>
                <span>下单后会自动出现在此</span>
              </div>
            )}
          </SectionPanel>
        </div>
      </div>

      {/* Ticker tape: horizontal scrolling price strip (the "trader" affordance). */}
      <div className="ticker-tape" role="navigation" aria-label="热门合约">
        {tape.length === 0 ? (
          <span className="ticker-tape__empty num">
            {apiOnline ? "加载合约..." : "等待 API..."}
          </span>
        ) : (
          tape.map((c) => (
            <button
              key={c.symbol}
              type="button"
              className={`ticker-tape__item ${symbol === c.symbol ? "is-on" : ""}`}
              onClick={() => setSymbol(c.symbol)}
              title={c.symbol}
            >
              <span className="ticker-tape__symbol">{c.base_asset}</span>
              <span className="ticker-tape__price num">
                ${formatNumber((c as any).last_price, 2) || "—"}
              </span>
            </button>
          ))
        )}
      </div>
    </div>
  );
}
