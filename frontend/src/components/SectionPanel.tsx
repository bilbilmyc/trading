/**
 * SectionPanel — common "card with a labelled header" shell.
 *
 * MarketsPage, OrderHistoryPage, RiskPage, and several others repeat the
 * same JSX: a 1px hairline card, a header bar (with title + optional
 * trailing action), and a scrollable body. v0.4 baseline extracted
 * that into this component so callers stop repeating 14 lines of inline
 * `style={{ border: '1px solid var(--border)', ... }}`.
 *
 * Props:
 *   title       — header text, uppercase, mono.
 *   trailing    — optional element to render on the right of the header
 *                 (e.g. count badge, refresh button, interval selector).
 *   children    — body content.
 *   scroll      — `'none' | 'sm' | 'md' | 'lg' | 'xl'` — wraps body in
 *                 `.scroll-cap` with the matching `--xl` modifier for
 *                 a fixed max-height.
 *   flex        — when true, the body uses `flex: 1; min-height: 0` so
 *                 the panel fills available height inside a flex column.
 */

import type { ReactNode } from "react";

type ScrollSize = "none" | "sm" | "md" | "lg" | "xl";

interface SectionPanelProps {
  title: ReactNode;
  trailing?: ReactNode;
  children: ReactNode;
  scroll?: ScrollSize;
  flex?: boolean;
  className?: string;
}

const SCROLL_CLASS: Record<ScrollSize, string> = {
  none: "",
  sm: "scroll-cap scroll-cap--sm",
  md: "scroll-cap scroll-cap--md",
  lg: "scroll-cap scroll-cap--lg",
  xl: "scroll-cap scroll-cap--xl",
};

export function SectionPanel({
  title,
  trailing,
  children,
  scroll = "none",
  flex,
  className,
}: SectionPanelProps) {
  return (
    <section
      className={`section-panel ${flex ? "section-panel--flex" : ""} ${className ?? ""}`}
    >
      <header className="section-panel__head">
        <span className="section-panel__title">{title}</span>
        {trailing ? <span className="section-panel__trailing">{trailing}</span> : null}
      </header>
      <div className={`section-panel__body ${SCROLL_CLASS[scroll]}`.trim()}>
        {children}
      </div>
    </section>
  );
}
