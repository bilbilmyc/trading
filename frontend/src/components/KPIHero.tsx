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
  /** Decorative icon chip (gradient square). */
  icon?: ReactNode;
  /** Icon chip gradient (CSS background). */
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

const GRADIENT_PRESETS: Record<string, string> = {
  indigo: "linear-gradient(135deg, #6366F1 0%, #8B5CF6 100%)",
  green: "linear-gradient(135deg, #22C55E 0%, #14B8A6 100%)",
  red: "linear-gradient(135deg, #EF4444 0%, #EC4899 100%)",
  cyan: "linear-gradient(135deg, #06B6D4 0%, #6366F1 100%)",
  orange: "linear-gradient(135deg, #F97316 0%, #EF4444 100%)",
  yellow: "linear-gradient(135deg, #EAB308 0%, #F97316 100%)",
  pink: "linear-gradient(135deg, #EC4899 0%, #8B5CF6 100%)",
};

/**
 * Hero KPI tile — the "Bloomberg big-number" treatment.
 * Designed to live in a 5-column strip across the top of dashboard pages.
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
            className="kpi-hero__icon"
            style={{
              background:
                GRADIENT_PRESETS[iconGradient] ?? iconGradient,
            }}
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
