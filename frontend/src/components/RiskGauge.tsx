import { memo } from "react";

interface RiskGaugeProps {
  /** 0..1 — fraction of the gauge to fill (clamped). */
  value: number;
  /** Optional label below the arc. */
  label?: string;
  /** Override the value string; otherwise `value * 100` with "%" suffix. */
  display?: string;
  /** Tiny status word above the big number. */
  caption?: string;
  /** When the value crosses this threshold the gauge flips to danger colour. */
  dangerAt?: number;
  /** When the value crosses this threshold the gauge flips to warning colour. */
  warnAt?: number;
  /** Arc size in pixels (diameter). Default 160. */
  size?: number;
}

function clamp01(n: number): number {
  if (!Number.isFinite(n)) return 0;
  if (n < 0) return 0;
  if (n > 1) return 1;
  return n;
}

/**
 * Semi-circular "speedometer" gauge used in Risk / Portfolio.
 * SVG-only, no chart library — same look in dark and light themes.
 */
export const RiskGauge = memo(function RiskGauge({
  value,
  label,
  display,
  caption,
  dangerAt = 0.7,
  warnAt = 0.4,
  size = 160,
}: RiskGaugeProps) {
  const pct = clamp01(value);
  const radius = size / 2 - 14;
  const cx = size / 2;
  const cy = size / 2 + 8;
  const startAngle = -180;
  const endAngle = 0;
  const totalArc = endAngle - startAngle;
  const filledArc = totalArc * pct;

  // Background track
  const bgStart = polar(cx, cy, radius, startAngle);
  const bgEnd = polar(cx, cy, radius, endAngle);
  const bgD = `M ${bgStart.x} ${bgStart.y} A ${radius} ${radius} 0 0 1 ${bgEnd.x} ${bgEnd.y}`;

  // Foreground (filled) arc — split into multiple segments to handle small
  // values cleanly.
  let fgD = "";
  if (pct > 0.001) {
    const filledEnd = startAngle + filledArc;
    const seg = polar(cx, cy, radius, filledEnd);
    const largeArc = filledArc > 180 ? 1 : 0;
    fgD = `M ${bgStart.x} ${bgStart.y} A ${radius} ${radius} 0 ${largeArc} 1 ${seg.x} ${seg.y}`;
  }

  // Determine colour.
  const color =
    pct >= dangerAt
      ? "var(--negative)"
      : pct >= warnAt
        ? "var(--warning)"
        : "var(--positive)";

  const tag = pct >= dangerAt ? "danger" : pct >= warnAt ? "warn" : "safe";

  return (
    <div className={`risk-gauge risk-gauge--${tag}`} style={{ width: size }}>
      <svg width={size} height={size / 2 + 24} viewBox={`0 0 ${size} ${size / 2 + 24}`}>
        <path d={bgD} stroke="var(--border)" strokeWidth="10" fill="none" strokeLinecap="round" />
        {fgD ? (
          <path
            d={fgD}
            stroke={color}
            strokeWidth="10"
            fill="none"
            strokeLinecap="round"
            style={{ filter: `drop-shadow(0 0 6px ${color})` }}
          />
        ) : null}
      </svg>
      <div className="risk-gauge__body">
        <span className="risk-gauge__caption">{caption}</span>
        <strong className="risk-gauge__value">{display ?? `${(pct * 100).toFixed(1)}%`}</strong>
        {label ? <span className="risk-gauge__label">{label}</span> : null}
      </div>
    </div>
  );
});

function polar(cx: number, cy: number, r: number, angleDeg: number) {
  const rad = (angleDeg * Math.PI) / 180;
  return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
}
