import { memo, useMemo } from "react";

export interface CurvePoint {
  timestamp: string;
  equity: number;
  trade_id?: string | null;
}

interface EquityCurveChartProps {
  curves: Record<string, CurvePoint[]>;   // strategy -> time series
  width: number;
  height: number;
}

const SERIES_COLORS = [
  "var(--chart-series-1)",
  "var(--chart-series-2)",
  "var(--chart-series-3)",
  "var(--chart-series-4)",
  "var(--chart-series-5)",
  "var(--chart-series-6)",
];

function useMemoLayout(curves: Record<string, CurvePoint[]>, width: number, height: number) {
  return useMemo(() => {
    const allPoints: CurvePoint[] = [];
    for (const series of Object.values(curves)) allPoints.push(...series);
    if (allPoints.length === 0) return null;
    let lo = Infinity;
    let hi = -Infinity;
    for (const p of allPoints) {
      if (p.equity < lo) lo = p.equity;
      if (p.equity > hi) hi = p.equity;
    }
    if (!isFinite(lo) || !isFinite(hi) || hi <= lo) {
      lo = 0;
      hi = 1;
    }
    const range = hi - lo;
    lo -= range * 0.1;
    hi += range * 0.1;
    const padTop = 16;
    const padBottom = 28;
    const padLeft = 8;
    const padRight = 8;
    const plotW = width - padLeft - padRight;
    const plotH = height - padTop - padBottom;
    return { lo, hi, padTop, padBottom, padLeft, padRight, plotW, plotH };
  }, [curves, width, height]);
}

const EquityCurveChartInner = memo(function EquityCurveChartInner({
  curves,
  width,
  height,
}: EquityCurveChartProps) {
  const layout = useMemoLayout(curves, width, height);
  if (!layout) {
    return <div className="equity-curve equity-curve--empty">暂无权益曲线数据</div>;
  }
  const { lo, hi, padTop, padBottom, padLeft, padRight, plotW, plotH } = layout;

  // Per-series x-axis mapping: combine all points, sort by ts, find min/max ts.
  let minTs = Infinity;
  let maxTs = -Infinity;
  for (const series of Object.values(curves)) {
    for (const p of series) {
      const t = new Date(p.timestamp).getTime();
      if (t < minTs) minTs = t;
      if (t > maxTs) maxTs = t;
    }
  }
  const tsRange = maxTs - minTs || 1;
  const xFor = (ts: string) => padLeft + ((new Date(ts).getTime() - minTs) / tsRange) * plotW;
  const yFor = (v: number) => padTop + (plotH * (hi - v)) / (hi - lo);
  const yTicks = Array.from({ length: 5 }).map((_, k) => {
    const v = lo + ((hi - lo) * k) / 4;
    return { v, y: yFor(v) };
  });
  const strategies = Object.keys(curves);

  return (
    <svg
      className="equity-curve"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="权益曲线"
    >
      {yTicks.map((t, i) => (
        <line
          key={i}
          x1={padLeft}
          x2={width - padRight}
          y1={t.y}
          y2={t.y}
          stroke="var(--chart-grid)"
          strokeWidth={0.5}
          strokeDasharray="2 4"
        />
      ))}
      {strategies.map((strategy, idx) => {
        const color = SERIES_COLORS[idx % SERIES_COLORS.length];
        const points = curves[strategy]
          .map((p) => `${xFor(p.timestamp)},${yFor(p.equity)}`)
          .join(" ");
        const last = curves[strategy][curves[strategy].length - 1];
        return (
          <g key={strategy}>
            <polyline
              points={points}
              fill="none"
              stroke={color}
              strokeWidth={1.6}
              opacity={0.95}
            />
            <circle
              cx={xFor(last.timestamp)}
              cy={yFor(last.equity)}
              r={3}
              fill={color}
            />
          </g>
        );
      })}
      {yTicks.map((t, i) => (
        <text
          key={`label-${i}`}
          x={width - padRight - 4}
          y={t.y + 3}
          className="equity-curve__label"
        >
          {t.v.toFixed(0)}
        </text>
      ))}
      {strategies.length > 0 && (
        <g>
          {strategies.map((strategy, idx) => (
            <g
              key={`legend-${strategy}`}
              transform={`translate(${padLeft + 4 + idx * 110}, ${padTop - 4})`}
            >
              <rect
                width={10}
                height={2}
                fill={SERIES_COLORS[idx % SERIES_COLORS.length]}
                y={4}
              />
              <text
                x={14}
                y={7}
                className="equity-curve__legend"
              >
                {strategy}
              </text>
            </g>
          ))}
        </g>
      )}
    </svg>
  );
});

export function EquityCurveChart(props: EquityCurveChartProps) {
  return <EquityCurveChartInner {...props} />;
}
