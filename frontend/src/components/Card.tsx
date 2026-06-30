import type { ReactNode } from "react";

type ColSpan =
  | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12;

interface CardProps {
  /** Optional header shown at the top of the card. */
  title?: string;
  /** Optional short description under the title. */
  subtitle?: string;
  /** Right-aligned slot in the header (e.g. status pill, action button). */
  trailing?: ReactNode;
  /** When false, the card has no internal padding — useful for charts. */
  padded?: boolean;
  /** When true, the card shows hover feedback (border + shadow). */
  hoverable?: boolean;
  /** When true, the card has a strong accent border. */
  accent?: boolean;
  /** Removes inner border-radius padding for content (e.g. tables). */
  flush?: boolean;
  /** Visual density. `compact` trims padding & gap; `loose` widens them. */
  density?: "compact" | "normal" | "loose";
  /** Grid-column span when placed inside `.page__grid--12`. */
  colSpan?: ColSpan;
  /** Disable the auto-lift on hover (e.g. for sticky panels). */
  static_?: boolean;
  /** Additional CSS class on the card root. */
  className?: string;
  children: ReactNode;
}

/**
 * Generic content container. Replaces the ad-hoc `.panel`, `.watchlist-card`,
 * `.cap-card`, `.preview-card`, and `.ai-report` containers with a single
 * uniform shell. Pair with `.page__grid--12` + `colSpan` for dashboard density.
 */
export function Card({
  title,
  subtitle,
  trailing,
  padded = true,
  hoverable = false,
  accent = false,
  flush = false,
  density = "normal",
  colSpan,
  static_ = false,
  className = "",
  children,
}: CardProps) {
  const cls = [
    "card",
    padded ? "card--padded" : "",
    density === "compact" ? "card--compact" : "",
    density === "loose" ? "card--loose" : "",
    hoverable ? "card--hoverable" : "",
    accent ? "card--accent" : "",
    flush ? "card--flush" : "",
    static_ ? "card--static" : "",
    colSpan ? `col-span-${colSpan}` : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <section className={cls}>
      {title || subtitle || trailing ? (
        <header className="card__header">
          <div className="stack--tight min-w-0">
            {title ? <h3 className="card__title">{title}</h3> : null}
            {subtitle ? <p className="card__subtitle">{subtitle}</p> : null}
          </div>
          {trailing ? <div className="card__trailing">{trailing}</div> : null}
        </header>
      ) : null}
      <div className={flush ? "card__body card__body--flush" : "card__body"}>{children}</div>
    </section>
  );
}
