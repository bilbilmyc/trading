import type { ReactNode } from "react";

type MetricTone = "default" | "positive" | "negative" | "warning" | "muted";

interface MetricProps {
  label: string;
  value: string;
  tone?: MetricTone;
  hint?: string;
}

const TONE_CLASS: Record<MetricTone, string> = {
  default: "",
  positive: "metric--positive",
  negative: "metric--negative",
  warning: "metric--warning",
  muted: "metric--muted",
};

export function Metric({ label, value, tone = "default", hint }: MetricProps) {
  return (
    <div className={`metric ${TONE_CLASS[tone]}`}>
      <span className="metric__label">{label}</span>
      <strong className="metric__value">{value}</strong>
      {hint ? <small className="metric__hint">{hint}</small> : null}
    </div>
  );
}

/**
 * AutoClip-style stat tile: gradient icon (gradient-brand) + big number + label
 * + optional change badge. Use this for top-of-page stat strips.
 */
interface MetricTileProps {
  label: string;
  value: string;
  icon: ReactNode;
  /** Optional % change badge (e.g. "+12%"). */
  change?: { value: string; tone?: "positive" | "negative" | "muted" };
  /** Override the default indigo→purple gradient with another gradient. */
  iconGradient?: "indigo" | "green" | "cyan" | "orange" | "pink" | "yellow" | "red";
}

const ICON_GRADIENT: Record<NonNullable<MetricTileProps["iconGradient"]>, string> = {
  indigo: "linear-gradient(135deg, #6366F1 0%, #8B5CF6 100%)",
  green: "linear-gradient(135deg, #22C55E 0%, #14B8A6 100%)",
  cyan: "linear-gradient(135deg, #06B6D4 0%, #6366F1 100%)",
  orange: "linear-gradient(135deg, #F97316 0%, #EF4444 100%)",
  pink: "linear-gradient(135deg, #EC4899 0%, #8B5CF6 100%)",
  yellow: "linear-gradient(135deg, #EAB308 0%, #F97316 100%)",
  red: "linear-gradient(135deg, #EF4444 0%, #EC4899 100%)",
};

const BADGE_TONE_CLASS: Record<NonNullable<MetricTileProps["change"]>["tone"] & string, string> = {
  positive: "badge--green",
  negative: "badge--red",
  muted: "badge--cyan",
};

export function MetricTile({ label, value, icon, change, iconGradient = "indigo" }: MetricTileProps) {
  return (
    <div className="metric-tile hover-lift">
      <div className="metric-tile__head">
        <span
          className="metric-tile__icon"
          style={{ background: ICON_GRADIENT[iconGradient] }}
        >
          {icon}
        </span>
        {change ? (
          <span className={`badge ${BADGE_TONE_CLASS[change.tone ?? "muted"]}`}>
            {change.value}
          </span>
        ) : null}
      </div>
      <div className="metric-tile__value">{value}</div>
      <div className="metric-tile__label">{label}</div>
    </div>
  );
}

interface StatusPillProps {
  state: "ok" | "bad" | "neutral" | "danger" | "safe";
  icon?: ReactNode;
  children: ReactNode;
}

export function StatusPill({ state, icon, children }: StatusPillProps) {
  return (
    <span className={`status-pill status-pill--${state}`}>
      {icon}
      {children}
    </span>
  );
}

interface SectionTitleProps {
  title: string;
  trailing?: ReactNode;
  subtitle?: string;
}

export function SectionTitle({ title, trailing, subtitle }: SectionTitleProps) {
  return (
    <header className="section-title">
      <div>
        <h3>{title}</h3>
        {subtitle ? <p>{subtitle}</p> : null}
      </div>
      {trailing}
    </header>
  );
}

interface EmptyStateProps {
  children: ReactNode;
  icon?: ReactNode;
}

export function EmptyState({ children, icon }: EmptyStateProps) {
  return (
    <div className="empty-state">
      {icon}
      <span>{children}</span>
    </div>
  );
}