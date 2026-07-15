/**
 * Live TopTicker — pulls from /api/v1/prices every 5s, falls back to dashes.
 *
 * The previous version (commit 0bc9714) shipped with hard-coded sample
 * prices which violated "monitoring" — the user has no way to tell real
 * from fake without watching the API logs. v0.4 wires it to the live
 * prices endpoint and shows "—" until the first response arrives.
 */

import { memo, useEffect, useState } from "react";

import { marketApi } from "../api/market";

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

export const TopTicker = memo(function TopTicker() {
  const [prices, setPrices] = useState<Record<string, number>>({});
  const [online, setOnline] = useState<boolean>(false);

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

  // Build the display list; missing prices render as "—" so the
  // marquee tells the user something, rather than echoing fake numbers.
  const items: TickerItem[] = DISPLAY_SYMBOLS.map((symbol) => ({
    symbol,
    price: prices[symbol] ?? null,
    // 24h change isn't in /prices; a future ticker-per-symbol call
    // can fill this in. For now we leave it null so the UI strips it.
    change: null,
  }));

  // Duplicate for the seamless marquee loop.
  const loop = [...items, ...items];

  return (
    <div className="top-ticker" role="marquee" aria-label="热门合约行情">
      <div className="top-ticker__track">
        {loop.map((item, i) => (
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
          </span>
        ))}
      </div>
    </div>
  );
});
