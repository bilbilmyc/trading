/**
 * Hairline progress bar — used by Sidebar and BotMonitorPage.
 *
 * Replaces inline-styled mini-bars that were duplicated in 3+ places.
 * Token-driven: all colors / widths come from CSS variables. Callers
 * pass a `gradient` only when they want a non-default (default is
 * muted indigo→purple).
 */

interface ProgressBarProps {
  label: string;
  value: string;
  /** 0..100 */
  pct: number;
  /** Optional CSS gradient for the filled portion. */
  gradient?: string;
}

const DEFAULT_GRADIENT =
  "linear-gradient(90deg, var(--accent) 0%, var(--accent-purple) 100%)";

export function ProgressBar({ label, value, pct, gradient }: ProgressBarProps) {
  const clamped = Math.max(0, Math.min(100, pct));
  return (
    <div className="progress-row">
      <div className="progress-row__head">
        <span className="progress-row__label">{label}</span>
        <span className="progress-row__value num">{value}</span>
      </div>
      <div
        className="progress-row__track"
        role="progressbar"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className="progress-row__fill"
          style={{
            width: `${clamped}%`,
            background: gradient ?? DEFAULT_GRADIENT,
          }}
        />
      </div>
    </div>
  );
}
