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
}

/**
 * Standard page header shared by every route page. Replaces the ad-hoc
 * `.page__header` blocks that were hand-rolled in each page.
 */
export function PageHeader({ eyebrow, title, subtitle, icon, actions }: PageHeaderProps) {
  return (
    <header className="page-header">
      <div className="page-header__text">
        {icon ? (
          <span className="page-header__icon page-header__icon--gradient page-header__icon--glow">
            {icon}
          </span>
        ) : null}
        {eyebrow ? <span className="page-header__eyebrow">{eyebrow}</span> : null}
        <h1 className="page-header__title">{title}</h1>
        {subtitle ? <p className="page-header__subtitle">{subtitle}</p> : null}
      </div>
      {actions ? <div className="page-header__actions">{actions}</div> : null}
    </header>
  );
}
