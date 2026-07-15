import { useEffect, useState, type ReactNode } from "react";

interface PageHeaderProps {
  /** Small uppercase label rendered above the title (e.g. "数据 · 行情"). */
  eyebrow?: string;
  /** Main h1 title. */
  title: string;
  /** Secondary description rendered below the title. */
  subtitle?: string;
  /** Decorative icon shown above the eyebrow. */
  icon?: ReactNode;
  /** Slot for action buttons (refresh, filters, etc.). */
  actions?: ReactNode;
  /** Visual density. `compact` tightens icon + title for dense dashboard rows. */
  density?: "default" | "compact";
  /** Optional background panel wrapper (used when the header sits inside a Card). */
  flush?: boolean;
  /**
   * Optional "data freshness" badge rendered to the right of the title.
   * Pass an epoch-ms timestamp of the most recent data fetch; the header
   * re-renders the relative label every second. Pass `null` to render a
   * muted "—" placeholder.
   */
  freshness?: { at: number | null; label?: string } | null;
}

function relativeAge(ts: number | null): string {
  if (ts === null) return "—";
  const diff = Math.max(0, Math.floor((Date.now() - ts) / 1000));
  if (diff < 5) return "刚刚";
  if (diff < 60) return `${diff}s 前`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m 前`;
  return `${Math.floor(diff / 3600)}h 前`;
}

function freshnessTone(ageSeconds: number | null): "fresh" | "stale" | "old" {
  if (ageSeconds === null) return "old";
  if (ageSeconds < 30) return "fresh";
  if (ageSeconds < 120) return "stale";
  return "old";
}

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  icon,
  actions,
  density = "default",
  flush = false,
  freshness,
}: PageHeaderProps) {
  // Re-render the freshness label every second so "3s 前" actually moves.
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!freshness) return;
    const id = window.setInterval(() => setTick((n) => n + 1), 1000);
    return () => window.clearInterval(id);
  }, [freshness]);

  const rootCls = [
    "page-header",
    density === "compact" ? "page-header--compact" : "",
    flush ? "page-header--flush" : "",
  ]
    .filter(Boolean)
    .join(" ");

  const ageSeconds =
    freshness && freshness.at !== null
      ? Math.max(0, Math.floor((Date.now() - freshness.at) / 1000))
      : freshness
      ? null
      : null;
  const tone = freshnessTone(ageSeconds);
  const freshnessAt = freshness ? freshness.at : null;
  const freshnessLabel = freshness
    ? `${freshness.label ?? "数据"} · ${relativeAge(freshness.at)}`
    : null;

  return (
    <header className={rootCls}>
      <div className="page-header__text min-w-0">
        {icon ? (
          <span className="page-header__icon page-header__icon--gradient page-header__icon--glow">
            {icon}
          </span>
        ) : null}
        {eyebrow ? <span className="page-header__eyebrow">{eyebrow}</span> : null}
        <div className="page-header__title-row">
          <h1 className="page-header__title text-balance">{title}</h1>
          {freshnessLabel ? (
            <span
              className={`page-header__freshness page-header__freshness--${tone}`}
              title={freshnessAt ? new Date(freshnessAt).toLocaleTimeString() : ""}
            >
              <span className="page-header__freshness-dot" aria-hidden="true" />
              {freshnessLabel}
            </span>
          ) : null}
        </div>
        {subtitle ? <p className="page-header__subtitle">{subtitle}</p> : null}
      </div>
      {actions ? <div className="page-header__actions">{actions}</div> : null}
    </header>
  );
}
