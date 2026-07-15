import type { ReactNode } from "react";
import { Sparkline } from "./Sparkline";

interface KPIHeroProps {
  /** Small uppercase label rendered above the big value. */
  label: string;
  /** Big mono value (raw — caller formats). */
  value: string;
  /** Optional trend pill showing change vs baseline. */
  delta?: { value: string; tone?: "positive" | "negative" | "muted" | "warning" | "default" };
  /** Optional mini sparkline at the bottom. */
  sparkline?: number[];
  /** Sparkline stroke override. */
  sparklineColor?: string;
  /** Supporting icon for fast scanning. */
  icon?: ReactNode;
  /** Semantic icon tone. Custom CSS colors remain supported for callers. */
  iconGradient?: string;
  /** Optional footer hint (e.g. "last 24h"). */
  hint?: string;
  /** Optional onClick to make the tile interactive. */
  onClick?: () => void;
  /** ARIA label override. */
  ariaLabel?: string;
}

const TONE_CLASS: Record<NonNullable<NonNullable<KPIHeroProps["delta"]>["tone"]>, string> = {
  positive: "kpi-hero__delta--up",
  negative: "kpi-hero__delta--down",
  muted: "kpi-hero__delta--muted",
  warning: "kpi-hero__delta--muted",
  default: "kpi-hero__delta--muted",
};

const ICON_TONES = new Set(["indigo", "green", "red", "cyan", "orange", "yellow", "pink"]);

/**
 * Compact terminal KPI. Icon hues are semantic and intentionally flat so the
 * values remain the strongest visual signal on the page.
 */
export function KPIHero({
  label,
  value,
  delta,
  sparkline,
  sparklineColor,
  icon,
  iconGradient = "indigo",
  hint,
  onClick,
  ariaLabel,
}: KPIHeroProps) {
  const Tag = onClick ? "button" : "div";
  const knownTone = ICON_TONES.has(iconGradient);

  return (
    <Tag
      className={`kpi-hero ${onClick ? "kpi-hero--clickable" : ""}`}
      onClick={onClick}
      aria-label={ariaLabel}
      type={onClick ? "button" : undefined}
    >
      <div className="kpi-hero__head">
        <span className="kpi-hero__label">{label}</span>
        {icon ? (
          <span
            className={`kpi-hero__icon ${knownTone ? `kpi-hero__icon--${iconGradient}` : ""}`}
            style={knownTone ? undefined : { background: iconGradient }}
            aria-hidden="true"
          >
            {icon}
          </span>
        ) : null}
      </div>
      <div className="kpi-hero__value">{value}</div>
      <div className="kpi-hero__foot">
        {delta ? (
          <span className={`kpi-hero__delta ${TONE_CLASS[delta.tone ?? "muted"]}`}>
            {delta.value}
          </span>
        ) : null}
        {hint ? <span className="kpi-hero__hint">{hint}</span> : null}
        {sparkline && sparkline.length > 1 ? (
          <span className="kpi-hero__sparkline">
            <Sparkline values={sparkline} color={sparklineColor} />
          </span>
        ) : null}
      </div>
    </Tag>
  );
}
