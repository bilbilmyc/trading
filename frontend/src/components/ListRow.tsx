import type { ReactNode } from "react";

export type ListRowLevel = "critical" | "error" | "warning" | "info" | "success";

interface ListRowProps {
  /** Optional left-side content (icon, marker dot, avatar, etc.). */
  leading?: ReactNode;
  /** Primary label. */
  title: ReactNode;
  /** Optional secondary line below the title. */
  subtitle?: ReactNode;
  /** Optional right-side content (badge, number, action). */
  trailing?: ReactNode;
  /** When true, the row is clickable and shows hover feedback. */
  onClick?: () => void;
  /** When true, the row is highlighted as the current selection. */
  active?: boolean;
  /** Optional level — controls the left border color (audit events, etc.). */
  level?: ListRowLevel;
  /** Additional class on the row root. */
  className?: string;
}

/**
 * Generic horizontal row used by signal/event/position/strategy lists.
 * Replaces `.signal-row`, `.event-row`, `.position-row`, `.strategy-row`,
 * and `.trade-row` with one shared component.
 */
export function ListRow({
  leading,
  title,
  subtitle,
  trailing,
  onClick,
  active = false,
  level,
  className = "",
}: ListRowProps) {
  const cls = [
    "list-row",
    onClick ? "is-clickable" : "",
    active ? "is-active" : "",
    level ? `list-row--${level}` : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  const interactiveProps = onClick
    ? { role: "button", tabIndex: 0, onClick, onKeyDown: (e: React.KeyboardEvent) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onClick();
        }
      }}
    : {};

  return (
    <div className={cls} {...interactiveProps}>
      {leading ? <div className="list-row__leading">{leading}</div> : null}
      <div className="list-row__body">
        <div className="list-row__title">{title}</div>
        {subtitle ? <div className="list-row__subtitle">{subtitle}</div> : null}
      </div>
      {trailing ? <div className="list-row__trailing">{trailing}</div> : null}
    </div>
  );
}
