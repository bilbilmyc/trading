import { memo } from "react";

interface SparklineProps {
  /** Sequence of values (will auto-normalize to its own range). */
  values: number[];
  /** Canvas size in pixels. Default 96×32 (md). */
  width?: number;
  height?: number;
  /** Stroke colour. Defaults to the brand accent. */
  color?: string;
  /** Render a translucent area fill below the line. */
  fill?: boolean;
  /** Force an "up" / "down" tone. Defaults to last - first direction. */
  tone?: "auto" | "up" | "down" | "muted";
}

/**
 * Tiny SVG sparkline used in KPIHero tiles and compact stat rows.
 * Pure presentational — no axes, no labels.
 */
export const Sparkline = memo(function Sparkline({
  values,
  width = 96,
  height = 32,
  color,
  fill = true,
  tone = "auto",
}: SparklineProps) {
  if (values.length < 2) {
    return <span className="sparkline sparkline--empty" style={{ width, height }} />;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const stepX = width / (values.length - 1);
  const padY = 2;
  const plotH = height - padY * 2;
  const points = values.map((v, i) => {
    const x = i * stepX;
    const y = padY + plotH - ((v - min) / range) * plotH;
    return `${x.toFixed(2)},${y.toFixed(2)}`;
  });
  const polyline = points.join(" ");
  const lastIndex = values.length - 1;
  const lastX = lastIndex * stepX;
  const lastY =
    padY + plotH - ((values[lastIndex] - min) / range) * plotH;
  const fillPoints = `0,${height} ${polyline} ${width},${height}`;

  const isUp =
    tone === "auto"
      ? values[lastIndex] >= values[0]
      : tone === "up";
  const isDown = tone === "down";
  const stroke =
    color ?? (isUp ? "var(--positive)" : isDown ? "var(--negative)" : "var(--accent)");

  return (
    <svg
      className="sparkline"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      aria-hidden="true"
    >
      {fill ? (
        <polygon points={fillPoints} fill={stroke} fillOpacity={0.14} />
      ) : null}
      <polyline
        points={polyline}
        fill="none"
        stroke={stroke}
        strokeWidth={1.6}
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <circle cx={lastX} cy={lastY} r={2.4} fill={stroke} />
    </svg>
  );
});
