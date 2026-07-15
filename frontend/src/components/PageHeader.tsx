import type { ReactNode } from "react";

interface PageHeaderProps {
  /** Small uppercase label retained for backwards-compatible call sites. */
  eyebrow?: string;
  /** Main page title kept in the document outline, but not shown as a banner. */
  title: string;
  /** Secondary description retained for backwards-compatible call sites. */
  subtitle?: string;
  /** Decorative icon retained for backwards-compatible call sites. */
  icon?: ReactNode;
  /** Page actions remain available without rendering the old title block. */
  actions?: ReactNode;
  /** Retained for backwards-compatible call sites. */
  density?: "default" | "compact";
  /** Retained for backwards-compatible call sites. */
  flush?: boolean;
  /** Retained for backwards-compatible call sites. */
  freshness?: { at: number | null; label?: string } | null;
}

/**
 * Keeps page titles accessible without rendering the redundant banner that
 * previously appeared above every screen. Actions are intentionally preserved
 * so refresh controls on list pages do not disappear with the old header.
 */
export function PageHeader({ title, actions }: PageHeaderProps) {
  return (
    <>
      <h1 className="sr-only">{title}</h1>
      {actions ? (
        <div className="page-header__actions page-header__actions--standalone">{actions}</div>
      ) : null}
    </>
  );
}
