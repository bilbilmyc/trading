import type { ReactNode } from "react";
import { Link } from "wouter";
import { Inbox } from "lucide-react";

interface EmptyStateAction {
  label: string;
  href?: string;
  onClick?: () => void;
  icon?: ReactNode;
}

interface EmptyStateProps {
  /** Optional icon. Defaults to Inbox. */
  icon?: ReactNode;
  /** Required — the headline ("暂无策略数据"). */
  title: string;
  /** Optional helper line under the title. */
  hint?: ReactNode;
  /** Single primary action button. */
  action?: EmptyStateAction;
  /** Visual density. `compact` = minimal padding, `iconic` = centered icon. */
  variant?: "default" | "compact" | "iconic";
  /** Optional slot for arbitrary content appended below. */
  children?: ReactNode;
  /** Forwarded to root for tests / layout overrides. */
  className?: string;
}

/**
 * Shared empty-state surface. Replaces ad-hoc `<div className="empty-state">`
 * blocks across pages. Visual treatment uses the AutoClip design language
 * (gradient icon chip + dashed border).
 */
export function EmptyState({
  icon,
  title,
  hint,
  action,
  variant = "default",
  children,
  className = "",
}: EmptyStateProps) {
  const cls = [
    "empty-state",
    variant === "compact" ? "empty-state--compact" : "",
    variant === "iconic" ? "empty-state--iconic" : "",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={cls} role="status" aria-live="polite">
      {variant === "iconic" ? (
        <span className="empty-state__icon-tile" aria-hidden="true">
          {icon ?? <Inbox size={18} strokeWidth={2} />}
        </span>
      ) : null}
      <strong className="truncate-1">{title}</strong>
      {hint ? <span>{hint}</span> : null}
      {children}
      {action ? (
        action.href ? (
          <Link
            href={action.href}
            className="btn btn--ghost btn--sm empty-state__action"
          >
            {action.icon}
            {action.label}
          </Link>
        ) : (
          <button
            type="button"
            className="btn btn--ghost btn--sm empty-state__action"
            onClick={action.onClick}
          >
            {action.icon}
            {action.label}
          </button>
        )
      ) : null}
    </div>
  );
}
