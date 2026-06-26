import { useMemo } from "react";

export interface Candle {
  open_time: string | number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface CandleChartProps {
  candles: Candle[];
  width?: number;
  height?: number;
  bullColor?: string;
  bearColor?: string;
}

/**
 * Lightweight SVG candlestick chart. No chart library dependency.
 * Auto-scales price axis to the candle range.
 */
export function CandleChart({
  candles,
  width = 720,
  height = 240,
  bullColor = "#22c55e",
  bearColor = "#ef4444",
}: CandleChartProps) {
  const layout = useMemo(() => {
    if (candles.length === 0) {
      return null;
    }
    const padTop = 16;
    const padBottom = 24;
    const padLeft = 8;
    const padRight = 56;
    const plotW = width - padLeft - padRight;
    const plotH = height - padTop - padBottom;
    let lo = Infinity;
    let hi = -Infinity;
    for (const c of candles) {
      if (c.low < lo) lo = c.low;
      if (c.high > hi) hi = c.high;
    }
    if (!isFinite(lo) || !isFinite(hi) || hi <= lo) {
      lo = 0;
      hi = 1;
    }
    const range = hi - lo;
    lo -= range * 0.05;
    hi += range * 0.05;
    const candleW = plotW / candles.length;
    const bodyW = Math.max(2, candleW * 0.6);
    return { padTop, padBottom, padLeft, padRight, plotW, plotH, lo, hi, candleW, bodyW };
  }, [candles, width, height]);

  if (!layout) {
    return (
      <div className="candle-chart candle-chart--empty">
        暂无 K 线数据
      </div>
    );
  }

  const yFor = (price: number) =>
    layout.padTop + (layout.plotH * (layout.hi - price)) / (layout.hi - layout.lo);
  const xFor = (i: number) => layout.padLeft + i * layout.candleW + layout.candleW / 2;

  // Y-axis ticks (5 levels)
  const yTicks = Array.from({ length: 5 }).map((_, k) => {
    const price = layout.lo + ((layout.hi - layout.lo) * k) / 4;
    return { price, y: yFor(price) };
  });

  return (
    <svg
      className="candle-chart"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="K 线图"
    >
      {/* Gridlines */}
      {yTicks.map((t, i) => (
        <line
          key={i}
          x1={layout.padLeft}
          x2={layout.padLeft + layout.plotW}
          y1={t.y}
          y2={t.y}
          stroke="#25305a"
          strokeWidth={0.5}
          strokeDasharray="2 4"
        />
      ))}
      {/* Candles */}
      {candles.map((c, i) => {
        const x = xFor(i);
        const isBull = c.close >= c.open;
        const color = isBull ? bullColor : bearColor;
        const yOpen = yFor(c.open);
        const yClose = yFor(c.close);
        const yHigh = yFor(c.high);
        const yLow = yFor(c.low);
        const bodyTop = Math.min(yOpen, yClose);
        const bodyH = Math.max(1, Math.abs(yClose - yOpen));
        return (
          <g key={i}>
            <line x1={x} x2={x} y1={yHigh} y2={yLow} stroke={color} strokeWidth={1} />
            <rect
              x={x - layout.bodyW / 2}
              y={bodyTop}
              width={layout.bodyW}
              height={bodyH}
              fill={color}
              opacity={isBull ? 0.85 : 0.85}
            />
          </g>
        );
      })}
      {/* Y-axis labels */}
      {yTicks.map((t, i) => (
        <text
          key={`label-${i}`}
          x={width - layout.padRight + 6}
          y={t.y + 3}
          className="candle-chart__label"
        >
          {t.price.toFixed(2)}
        </text>
      ))}
    </svg>
  );
}