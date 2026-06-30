import { useCallback, useEffect, useState } from "react";
import { Link } from "wouter";
import { RefreshCw, Star, X } from "lucide-react";

import { api } from "../api";
import { Card } from "../components/Card";
import { PageHeader } from "../components/PageHeader";

interface Ticker {
  symbol: string;
  exchange: string;
  last_price?: number;
  price_change_pct_24h?: number;
  volume_24h?: number;
}

const KNOWN_SOURCES = [
  { value: "binance_usdm", label: "Binance USDⓈ-M" },
  { value: "okx_swap", label: "OKX 永续" },
  { value: "bitget_usdt_futures", label: "Bitget USDT 永续" },
];

const STORAGE_KEY = "quant_trader_watchlist_v1";

type Exchange = "binance_usdm" | "okx_swap" | "bitget_usdt_futures";

interface WatchlistItem {
  symbol: string;
  exchange: Exchange;
}

function loadWatchlist(): WatchlistItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return defaultWatchlist();
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return defaultWatchlist();
    return parsed;
  } catch {
    return defaultWatchlist();
  }
}

function defaultWatchlist(): WatchlistItem[] {
  return [
    { symbol: "BTCUSDT", exchange: "binance_usdm" },
    { symbol: "ETHUSDT", exchange: "binance_usdm" },
    { symbol: "SOLUSDT", exchange: "binance_usdm" },
  ];
}

function saveWatchlist(items: WatchlistItem[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
}

function formatPrice(v: number | undefined): string {
  if (v === undefined) return "--";
  return `$${v.toFixed(v > 1000 ? 1 : 4)}`;
}

export function WatchlistPage() {
  const [items, setItems] = useState<WatchlistItem[]>(loadWatchlist);
  const [prices, setPrices] = useState<Record<string, Ticker | null>>({});
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [newSymbol, setNewSymbol] = useState("");
  const [newExchange, setNewExchange] = useState<Exchange>("binance_usdm");

  const refresh = useCallback(async () => {
    setRefreshing(true);
    setError("");
    try {
      const next: Record<string, Ticker | null> = {};
      for (const item of items) {
        try {
          const t = await api.ticker(item.exchange, item.symbol);
          next[`${item.exchange}:${item.symbol}`] = t as Ticker;
        } catch {
          next[`${item.exchange}:${item.symbol}`] = null;
        }
      }
      setPrices(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : "刷新失败");
    } finally {
      setRefreshing(false);
    }
  }, [items]);

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, 10_000);
    return () => window.clearInterval(id);
  }, [refresh]);

  function addItem() {
    const sym = newSymbol.trim().toUpperCase();
    if (!sym) return;
    const next = [...items, { symbol: sym, exchange: newExchange }];
    setItems(next);
    saveWatchlist(next);
    setNewSymbol("");
  }

  function removeItem(idx: number) {
    const next = items.filter((_, i) => i !== idx);
    setItems(next);
    saveWatchlist(next);
  }

  return (
    <div className="page page--watchlist">
      <PageHeader
        icon={<Star size={18} />}
        eyebrow="自选观察"
        title="Watchlist"
        subtitle="多币种多交易所实时行情 · 10s 自动刷新"
        actions={
          <button
            type="button"
            className="action action--primary"
            onClick={refresh}
            disabled={refreshing}
          >
            <RefreshCw size={14} className={refreshing ? "spin" : ""} />
            {refreshing ? "刷新中..." : "刷新"}
          </button>
        }
      />

      <Card title="添加自选" subtitle="输入合约代码 + 选择交易所">
        <div className="form-grid form-grid--inline">
          <label className="field">
            <span>合约代码</span>
            <input
              value={newSymbol}
              onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
              placeholder="BTCUSDT"
              onKeyDown={(e) => e.key === "Enter" && addItem()}
            />
          </label>
          <label className="field">
            <span>交易所</span>
            <select
              value={newExchange}
              onChange={(e) => setNewExchange(e.target.value as Exchange)}
            >
              {KNOWN_SOURCES.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </label>
          <div className="field">
            <button
              type="button"
              className="action action--primary"
              onClick={addItem}
              disabled={!newSymbol.trim()}
            >
              添加
            </button>
          </div>
        </div>
        {error ? <div className="notice notice--error">{error}</div> : null}
      </Card>

      <Card title={`自选 (${items.length})`} subtitle="点击合约代码进入行情">
        {items.length === 0 ? (
          <div className="empty-state">
            <strong>尚无自选</strong>
            <span>在上方表单里添加合约即可开始观察</span>
          </div>
        ) : (
          <div className="watchlist-grid">
            {items.map((item, idx) => {
              const key = `${item.exchange}:${item.symbol}`;
              const t = prices[key];
              const change = t?.price_change_pct_24h;
              const positive = change !== undefined && change >= 0;
              return (
                <article key={key} className="card card--padded card--hoverable">
                  <div className="watchlist-card__head">
                    <Link
                      href={`/markets?source=${item.exchange}&symbol=${item.symbol}`}
                      className="watchlist-card__symbol"
                    >
                      <strong>{item.symbol}</strong>
                      <small>{item.exchange}</small>
                    </Link>
                    <button
                      type="button"
                      className="watchlist-card__remove"
                      onClick={() => removeItem(idx)}
                      title="移除"
                      aria-label={`移除 ${item.symbol}`}
                    >
                      <X size={14} />
                    </button>
                  </div>
                  {t ? (
                    <div className="watchlist-card__price">
                      <span className="watchlist-card__last">{formatPrice(t.last_price)}</span>
                      {change !== undefined ? (
                        <span
                          className={`watchlist-card__change ${positive ? "text-positive" : "text-negative"}`}
                        >
                          {positive ? "▲" : "▼"} {Math.abs(change).toFixed(2)}%
                        </span>
                      ) : null}
                    </div>
                  ) : (
                    <div className="watchlist-card__loading">加载中…</div>
                  )}
                </article>
              );
            })}
          </div>
        )}
      </Card>
    </div>
  );
}
