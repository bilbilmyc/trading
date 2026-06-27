import { memo, useMemo } from "react";

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

function useMemoLayout(
  candles: Candle[],
  width: number,
  height: number,
) {
  return useMemo(() => {
    if (candles.length === 0) return null;
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
}

interface ChartSvgProps {
  candles: Candle[];
  layout: ReturnType<typeof useMemoLayout>;
  width: number;
  height: number;
  bullColor: string;
  bearColor: string;
}

const ChartSvg = memo(function ChartSvg({
  candles,
  layout,
  width,
  height,
  bullColor,
  bearColor,
}: ChartSvgProps) {
  if (!layout) {
    return <div className="candle-chart candle-chart--empty">暂无 K 线数据</div>;
  }
  const { padTop, padBottom, padLeft, padRight, plotH, lo, hi, candleW, bodyW } = layout;
  const xFor = (i: number) => padLeft + i * candleW + candleW / 2;
  const yFor = (price: number) => padTop + (plotH * (hi - price)) / (hi - lo);
  const yTicks = Array.from({ length: 5 }).map((_, k) => {
    const price = lo + ((hi - lo) * k) / 4;
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
      {yTicks.map((t, i) => (
        <line
          key={i}
          x1={padLeft}
          x2={width - 8}
          y1={t.y}
          y2={t.y}
          stroke="#25305a"
          strokeWidth={0.5}
          strokeDasharray="2 4"
        />
      ))}
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
              x={x - bodyW / 2}
              y={bodyTop}
              width={bodyW}
              height={bodyH}
              fill={color}
              opacity={0.85}
            />
          </g>
        );
      })}
      {yTicks.map((t, i) => (
        <text
          key={`label-${i}`}
          x={width - 6}
          y={t.y + 3}
          className="candle-chart__label"
        >
          {t.price.toFixed(2)}
        </text>
      ))}
    </svg>
  );
});

export function CandleChart({
  candles,
  width = 720,
  height = 240,
  bullColor = "#22c55e",
  bearColor = "#ef4444",
}: CandleChartProps) {
  const layout = useMemoLayout(candles, width, height);
  return (
    <ChartSvg
      candles={candles}
      layout={layout}
      width={width}
      height={height}
      bullColor={bullColor}
      bearColor={bearColor}
    />
  );
}
