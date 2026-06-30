import { memo, useEffect, useState } from "react";

interface TickerItem {
  symbol: string;
  price: number;
  change: number;
}

/**
 * Static default sample so the strip never reads empty during boot.
 * In production this would come from a market-data SSE; we render the
 * fallback inline to keep the layout stable.
 */
const SAMPLE_ITEMS: TickerItem[] = [
  { symbol: "BTCUSDT", price: 97234.5, change: 1.84 },
  { symbol: "ETHUSDT", price: 3842.1, change: -0.92 },
  { symbol: "SOLUSDT", price: 198.32, change: 3.5 },
  { symbol: "BNBUSDT", price: 712.4, change: 0.42 },
  { symbol: "XRPUSDT", price: 2.351, change: -1.2 },
  { symbol: "ADAUSDT", price: 1.084, change: 2.1 },
  { symbol: "DOGEUSDT", price: 0.382, change: 5.7 },
  { symbol: "AVAXUSDT", price: 42.51, change: -2.3 },
  { symbol: "LINKUSDT", price: 22.14, change: 1.5 },
  { symbol: "DOTUSDT", price: 8.722, change: -0.5 },
];

/**
 * Horizontal-scrolling marquee of last prices.
 * Duplicated content with a CSS animation; pure render, no JS animation loop.
 */
export const TopTicker = memo(function TopTicker() {
  const [items] = useState<TickerItem[]>(SAMPLE_ITEMS);

  // (Hook retained so future SSE wiring is a one-liner.)
  useEffect(() => {
    /* no-op placeholder for future live data hook */
  }, []);

  // Duplicate the array so the marquee loop is visually seamless.
  const loop = [...items, ...items];

  return (
    <div className="top-ticker" role="marquee" aria-label="热门合约行情">
      <div className="top-ticker__track">
        {loop.map((item, i) => {
          const up = item.change >= 0;
          return (
            <span className="top-ticker__item" key={`${item.symbol}-${i}`}>
              <strong className="top-ticker__symbol">{item.symbol}</strong>
              <span className="top-ticker__price">
                ${item.price >= 1000
                  ? item.price.toLocaleString("en-US", { maximumFractionDigits: 2 })
                  : item.price.toFixed(4)}
              </span>
              <span
                className={`top-ticker__change ${up ? "is-up" : "is-down"}`}
                data-tone={up ? "up" : "down"}
              >
                {up ? "▲" : "▼"} {Math.abs(item.change).toFixed(2)}%
              </span>
            </span>
          );
        })}
      </div>
    </div>
  );
});
