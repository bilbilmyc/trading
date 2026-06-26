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