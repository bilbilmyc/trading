import type { ReactNode } from "react";

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
}

/**
 * Standard page header shared by every route page. Replaces the ad-hoc
 * `.page__header` blocks that were hand-rolled in each page.
 */
export function PageHeader({
  eyebrow,
  title,
  subtitle,
  icon,
  actions,
  density = "default",
  flush = false,
}: PageHeaderProps) {
  const rootCls = [
    "page-header",
    density === "compact" ? "page-header--compact" : "",
    flush ? "page-header--flush" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <header className={rootCls}>
      <div className="page-header__text min-w-0">
        {icon ? (
          <span className="page-header__icon page-header__icon--gradient page-header__icon--glow">
            {icon}
          </span>
        ) : null}
        {eyebrow ? <span className="page-header__eyebrow">{eyebrow}</span> : null}
        <h1 className="page-header__title text-balance">{title}</h1>
        {subtitle ? <p className="page-header__subtitle">{subtitle}</p> : null}
      </div>
      {actions ? <div className="page-header__actions">{actions}</div> : null}
    </header>
  );
}
