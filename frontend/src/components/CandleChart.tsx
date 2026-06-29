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
  /** Override bull color (defaults to var(--chart-bull)). */
  bullColor?: string;
  /** Override bear color (defaults to var(--chart-bear)). */
  bearColor?: string;
  /** Show moving average overlays. Defaults to [20, 60]. Pass [] to disable. */
  ma_periods?: number[];
  /** Show volume bars at the bottom. Default true. */
  show_volume?: boolean;
}

/** Token-based MA palette — auto-adapts to current theme via CSS variables. */
const MA_COLORS = ["var(--chart-ma-1)", "var(--chart-ma-2)", "var(--chart-ma-3)"];

function sma(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    out.push(i + 1 >= period ? sum / period : null);
  }
  return out;
}

function useMemoLayout(
  candles: Candle[],
  width: number,
  height: number,
  show_volume: boolean,
) {
  return useMemo(() => {
    if (candles.length === 0) return null;
    const padTop = 16;
    const padBottom = 24;
    const padLeft = 8;
    const padRight = 56;
    const volumeHeight = show_volume ? Math.max(40, height * 0.18) : 0;
    const plotH = height - padTop - padBottom - volumeHeight;
    const plotW = width - padLeft - padRight;
    let lo = Infinity;
    let hi = -Infinity;
    let volMax = 0;
    for (const c of candles) {
      if (c.low < lo) lo = c.low;
      if (c.high > hi) hi = c.high;
      if (c.volume && c.volume > volMax) volMax = c.volume;
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
    return {
      padTop, padBottom, padLeft, padRight,
      plotW, plotH, volumeHeight,
      lo, hi, candleW, bodyW, volMax,
    };
  }, [candles, width, height, show_volume]);
}

interface ChartSvgProps {
  candles: Candle[];
  layout: ReturnType<typeof useMemoLayout>;
  width: number;
  height: number;
  bullColor: string;
  bearColor: string;
  ma_periods: number[];
  show_volume: boolean;
}

const ChartSvg = memo(function ChartSvg({
  candles,
  layout,
  width,
  height,
  bullColor,
  bearColor,
  ma_periods,
  show_volume,
}: ChartSvgProps) {
  if (!layout) {
    return <div className="candle-chart candle-chart--empty">暂无 K 线数据</div>;
  }
  const {
    padTop, padBottom, padLeft, padRight,
    plotH, plotW, volumeHeight,
    lo, hi, candleW, bodyW, volMax,
  } = layout;
  const xFor = (i: number) => padLeft + i * candleW + candleW / 2;
  const yFor = (price: number) => padTop + (plotH * (hi - price)) / (hi - lo);
  const closes = candles.map((c) => c.close);
  const yTicks = Array.from({ length: 5 }).map((_, k) => {
    const price = lo + ((hi - lo) * k) / 4;
    return { price, y: yFor(price) };
  });
  const volBottomY = padTop + plotH + 4;
  const volTopY = padTop + plotH + volumeHeight - 4;
  const volYFor = (v: number) => {
    if (volMax <= 0) return volBottomY;
    return volBottomY + (volTopY - volBottomY) * (1 - v / volMax);
  };

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
          stroke="var(--chart-grid)"
          strokeWidth={0.5}
          strokeDasharray="2 4"
        />
      ))}

      {/* MA overlays */}
      {ma_periods.map((period, idx) => {
        const ma = sma(closes, period);
        const color = MA_COLORS[idx % MA_COLORS.length];
        const points = ma
          .map((v, i) => (v === null ? null : `${xFor(i)},${yFor(v)}`))
          .filter((s): s is string => s !== null)
          .join(" ");
        return (
          <polyline
            key={`ma-${period}`}
            points={points}
            fill="none"
            stroke={color}
            strokeWidth={1.2}
            opacity={0.85}
          />
        );
      })}

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

      {/* Volume bars */}
      {show_volume && candles.map((c, i) => {
        if (!c.volume || volMax <= 0) return null;
        const x = xFor(i);
        const yTop = volYFor(c.volume);
        const isBull = c.close >= c.open;
        const color = isBull ? bullColor : bearColor;
        return (
          <rect
            key={`vol-${i}`}
            x={x - bodyW / 2}
            y={yTop}
            width={bodyW}
            height={volBottomY - yTop}
            fill={color}
            opacity={0.3}
          />
        );
      })}

      {/* Y-axis labels (price) */}
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

      {/* MA legend */}
      {ma_periods.length > 0 && (
        <g>
          {ma_periods.map((period, idx) => (
            <g key={`legend-${period}`} transform={`translate(${padLeft + 4 + idx * 60}, ${padTop - 4})`}>
              <rect width={10} height={2} fill={MA_COLORS[idx % MA_COLORS.length]} y={4} />
              <text x={14} y={7} className="candle-chart__label">MA{period}</text>
            </g>
          ))}
        </g>
      )}
    </svg>
  );
});

export function CandleChart({
  candles,
  width = 720,
  height = 240,
  bullColor = "var(--chart-bull)",
  bearColor = "var(--chart-bear)",
  ma_periods = [20, 60],
  show_volume = true,
}: CandleChartProps) {
  const layout = useMemoLayout(candles, width, height, show_volume);
  return (
    <ChartSvg
      candles={candles}
      layout={layout}
      width={width}
      height={height}
      bullColor={bullColor}
      bearColor={bearColor}
      ma_periods={ma_periods}
      show_volume={show_volume}
    />
  );
}
