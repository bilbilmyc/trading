/**
 * Live TopTicker — pulls from /api/v1/prices every 5s, falls back to dashes.
 *
 * The previous version (commit 0bc9714) shipped with hard-coded sample
 * prices which violated "monitoring" — the user has no way to tell real
 * from fake without watching the API logs. v0.4 wires it to the live
 * prices endpoint and shows "—" until the first response arrives.
 *
 * v0.4.1 adds a static "venue strip" on the left that polls
 * `/api/v1/health/venues` every 15s. Each venue gets a colored dot:
 *   - green: public API reachable
 *   - red  : public API failed (network/auth/region)
 *   - yellow: public OK, private probe failed (or vice versa)
 *   - grey : disabled or unconfigured
 * Hover for the venue's full status (testnet, clock skew, error).
 *
 * v0.4.2 augments each marquee item with a 24h change pill sourced from
 * `/api/v1/market/top-movers` (server-side cached 20s). The pill
 * renders nothing when the field is null (so adapters that don't
 * surface `priceChangePercent` stay quiet).
 */

import { memo, useEffect, useState } from "react";

import { marketApi } from "../api/market";
import { metaApi, type VenueHealth } from "../api/meta";

interface TickerItem {
  symbol: string;
  price: number | null;
  /** 24h change in percent (best-effort). */
  change: number | null;
}

/** Display order — the user-visible watchlist. */
const DISPLAY_SYMBOLS: string[] = [
  "BTCUSDT",
  "ETHUSDT",
  "SOLUSDT",
  "BNBUSDT",
  "XRPUSDT",
  "ADAUSDT",
  "DOGEUSDT",
  "AVAXUSDT",
  "LINKUSDT",
  "DOTUSDT",
];

const POLL_INTERVAL_MS = 5_000;
const VENUE_POLL_INTERVAL_MS = 15_000;
const MOVERS_POLL_INTERVAL_MS = 30_000;

/** Short label for the venue strip. Keeps the strip narrow. */
const VENUE_SHORT: Record<string, string> = {
  binance: "BIN",
  binance_usdm: "BIN",
  okx: "OKX",
  okx_swap: "OKX",
  bitget: "BIT",
  bitget_usdt_futures: "BIT",
};

function shortName(venue: string): string {
  return VENUE_SHORT[venue] ?? venue.slice(0, 3).toUpperCase();
}

function dotState(v: VenueHealth | undefined): "ok" | "fail" | "degraded" | "off" {
  if (!v) return "off";
  if (!v.enabled) return "off";
  if (!v.public_api_ok) return "fail";
  // Public OK but private failed => partial; user is logged in but order POSTs are failing.
  if (v.private_api_ok === false) return "degraded";
  return "ok";
}

function dotTitle(v: VenueHealth | undefined, name: string): string {
  if (!v) return `${name} — 未配置`;
  if (!v.enabled) return `${name} — 已禁用`;
  if (!v.public_api_ok) {
    return `${name} — 公开 API 失败${v.public_api_error ? `: ${v.public_api_error}` : ""}`;
  }
  if (v.private_api_ok === false) {
    return `${name} — 私有 API 失败${v.private_api_error ? `: ${v.private_api_error}` : ""}（可查行情，无法下单）`;
  }
  const skew = v.clock_skew_ms !== null ? ` · 时钟偏差 ${v.clock_skew_ms}ms` : "";
  const net = v.use_testnet ? " · testnet" : "";
  return `${name} — 正常${net}${skew}`;
}

function formatChange(pct: number | null): {
  text: string;
  cls: "is-up" | "is-down" | "is-flat" | "";
} {
  if (pct === null || pct === undefined) return { text: "", cls: "" };
  if (pct > 0.005) return { text: `+${pct.toFixed(2)}%`, cls: "is-up" };
  if (pct < -0.005) return { text: `${pct.toFixed(2)}%`, cls: "is-down" };
  return { text: `${pct.toFixed(2)}%`, cls: "is-flat" };
}

export const TopTicker = memo(function TopTicker() {
  const [prices, setPrices] = useState<Record<string, number>>({});
  const [online, setOnline] = useState<boolean>(false);
  const [venues, setVenues] = useState<Record<string, VenueHealth>>({});
  const [changes, setChanges] = useState<Record<string, number>>({});

  useEffect(() => {
    let cancelled = false;
    const id = window.setInterval(async () => {
      try {
        const data = await marketApi.prices();
        if (!cancelled) {
          setPrices(data);
          setOnline(true);
        }
      } catch {
        if (!cancelled) setOnline(false);
      }
    }, POLL_INTERVAL_MS);
    // First read immediately so users don't see dashes on a warm cache.
    void (async () => {
      try {
        const data = await marketApi.prices();
        if (!cancelled) {
          setPrices(data);
          setOnline(true);
        }
      } catch {
        if (!cancelled) setOnline(false);
      }
    })();
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const data = await metaApi.venueHealth();
        if (!cancelled) setVenues(data.venues);
      } catch {
        // Silent: a stale dot is better than no ticker at all.
      }
    };
    void tick();
    const id = window.setInterval(tick, VENUE_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    const tick = async () => {
      try {
        const data = await marketApi.topMovers({ symbols: DISPLAY_SYMBOLS });
        if (cancelled) return;
        const next: Record<string, number> = {};
        for (const it of data.items) {
          if (it.change_pct_24h !== null && it.change_pct_24h !== undefined) {
            next[it.symbol] = it.change_pct_24h;
          }
        }
        setChanges(next);
      } catch {
        // Silent: no change pill is fine.
      }
    };
    void tick();
    const id = window.setInterval(tick, MOVERS_POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, []);

  // Build the display list; missing prices render as "—" so the
  // marquee tells the user something, rather than echoing fake numbers.
  const items: TickerItem[] = DISPLAY_SYMBOLS.map((symbol) => ({
    symbol,
    price: prices[symbol] ?? null,
    change: changes[symbol] ?? null,
  }));

  // Duplicate for the seamless marquee loop.
  const loop = [...items, ...items];

  const venueEntries = Object.entries(venues);

  return (
    <div className="top-ticker" role="marquee" aria-label="热门合约行情">
      {venueEntries.length > 0 ? (
        <div className="top-ticker__venues" aria-label="交易所连接状态">
          {venueEntries.map(([name, v]) => {
            const s = dotState(v);
            return (
              <span
                key={name}
                className={`top-ticker__venue top-ticker__venue--${s}`}
                title={dotTitle(v, name)}
              >
                <span className="top-ticker__venue-dot" aria-hidden="true" />
                {shortName(name)}
              </span>
            );
          })}
        </div>
      ) : null}
      <div className="top-ticker__track">
        {loop.map((item, i) => {
          const chg = formatChange(item.change);
          return (
            <span className="top-ticker__item" key={`${item.symbol}-${i}`}>
              {online && i === 0 ? (
                <span className="pulse-dot--live" aria-hidden="true" />
              ) : null}
              <strong className="top-ticker__symbol">{item.symbol}</strong>
              <span className="top-ticker__price num">
                {item.price === null
                  ? "—"
                  : item.price >= 1000
                    ? item.price.toLocaleString("en-US", { maximumFractionDigits: 2 })
                    : item.price.toFixed(4)}
              </span>
              {chg.text ? (
                <span className={`top-ticker__change ${chg.cls}`}>{chg.text}</span>
              ) : null}
            </span>
          );
        })}
      </div>
    </div>
  );
});
