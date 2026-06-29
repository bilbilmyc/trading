import { useMemo } from "react";

export interface OrderBookLevel {
  price: number;
  quantity: number;
}

interface OrderBookDepthProps {
  bids: OrderBookLevel[];   // sorted desc by price
  asks: OrderBookLevel[];   // sorted asc by price
  width?: number;
  height?: number;
}

/**
 * SVG-based order book depth chart.
 * Bids on the left (green), asks on the right (red).
 * Cumulative quantity at each price level.
 */
export function OrderBookDepth({
  bids,
  asks,
  width = 480,
  height = 200,
}: OrderBookDepthProps) {
  const layout = useMemo(() => {
    if (bids.length === 0 && asks.length === 0) return null;
    const allPrices = [...bids.map((b) => b.price), ...asks.map((a) => a.price)];
    if (allPrices.length === 0) return null;
    const minPrice = Math.min(...allPrices);
    const maxPrice = Math.max(...allPrices);
    if (minPrice === maxPrice) return null;
    const range = maxPrice - minPrice;
    const pad = range * 0.05;
    const lo = minPrice - pad;
    const hi = maxPrice + pad;

    // Cumulative quantities (sorted outward from mid).
    const sortedBids = [...bids].sort((a, b) => a.price - b.price);  // asc
    const sortedAsks = [...asks].sort((a, b) => a.price - b.price);

    let cumBid = 0;
    const bidCum = sortedBids.map((b) => {
      cumBid += b.quantity;
      return { price: b.price, cum: cumBid };
    });

    let cumAsk = 0;
    const askCum = sortedAsks.map((a) => {
      cumAsk += a.quantity;
      return { price: a.price, cum: cumAsk };
    });

    const maxCum = Math.max(
      bidCum.length ? bidCum[bidCum.length - 1].cum : 0,
      askCum.length ? askCum[askCum.length - 1].cum : 0
    );
    if (maxCum === 0) return null;

    return { lo, hi, maxCum, bidCum, askCum };
  }, [bids, asks]);

  if (!layout) {
    return <div className="depth-chart depth-chart--empty">暂无挂单数据</div>;
  }

  const { lo, hi, maxCum, bidCum, askCum } = layout;
  const padTop = 16;
  const padBottom = 24;
  const padLeft = 8;
  const padRight = 8;
  const plotW = width - padLeft - padRight;
  const plotH = height - padTop - padBottom;
  const midPrice = (Math.max(bids[bids.length - 1]?.price ?? 0, asks[0]?.price ?? 0) +
                   Math.min(asks[0]?.price ?? Infinity, bids[bids.length - 1]?.price ?? Infinity)) / 2 ||
                  (bids[0]?.price + asks[0]?.price) / 2;

  const xFor = (price: number) =>
    padLeft + ((price - lo) / (hi - lo)) * plotW;
  const yFor = (cum: number) =>
    padTop + plotH - (cum / maxCum) * plotH;

  // Build bid path (descending back from max).
  const bidPoints = [...bidCum].reverse();

  return (
    <svg
      className="depth-chart"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="订单簿深度图"
    >
      {/* Mid price line */}
      {midPrice > 0 && midPrice >= lo && midPrice <= hi && (
        <line
          x1={xFor(midPrice)}
          x2={xFor(midPrice)}
          y1={padTop}
          y2={padTop + plotH}
          stroke="var(--chart-axis)"
          strokeWidth={1}
          strokeDasharray="2 3"
        />
      )}

      {/* Bid area (left of mid) */}
      {bidPoints.length > 0 && (
        <path
          d={[
            `M ${xFor(hi)} ${yFor(0)}`,
            ...bidPoints.map(
              (p) => `L ${xFor(p.price)} ${yFor(p.cum)}`
            ),
            `L ${xFor(midPrice)} ${yFor(0)}`,
            "Z",
          ].join(" ")}
          fill="var(--chart-bull-soft)"
          stroke="var(--chart-bull)"
          strokeWidth={1.5}
        />
      )}

      {/* Ask area (right of mid) */}
      {askCum.length > 0 && (
        <path
          d={[
            `M ${xFor(lo)} ${yFor(0)}`,
            ...askCum.map(
              (p) => `L ${xFor(p.price)} ${yFor(p.cum)}`
            ),
            `L ${xFor(midPrice)} ${yFor(0)}`,
            "Z",
          ].join(" ")}
          fill="var(--chart-bear-soft)"
          stroke="var(--chart-bear)"
          strokeWidth={1.5}
        />
      )}

      {/* Mid price label */}
      {midPrice > 0 && midPrice >= lo && midPrice <= hi && (
        <text
          x={xFor(midPrice)}
          y={padTop + 12}
          className="depth-chart__label"
          textAnchor="middle"
        >
          {midPrice.toFixed(2)}
        </text>
      )}
    </svg>
  );
}