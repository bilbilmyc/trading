import { useEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";

interface ExpandModalProps {
  /** Controls visibility. Pair with `useExpandable()`. */
  isOpen: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  /** Optional right-aligned slot in the modal head (e.g. filter chips). */
  toolbar?: ReactNode;
  children: ReactNode;
}

/**
 * Full-viewport modal used to display the un-capped version of a list/table
 * that was scroll-capped on the page. Closes on Esc, backdrop click, or X.
 *
 * Body scroll is locked while open. The modal mounts into `document.body`
 * via a portal so it escapes any `overflow: hidden` ancestor.
 */
export function ExpandModal({
  isOpen,
  onClose,
  title,
  subtitle,
  toolbar,
  children,
}: ExpandModalProps) {
  const closeRef = useRef<HTMLButtonElement | null>(null);

  // Esc to close + body scroll lock while open.
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    // Auto-focus the close button for keyboard users.
    closeRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previousOverflow;
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return createPortal(
    <div
      className="modal-backdrop"
      onClick={(e) => {
        // Close only when the backdrop itself is clicked, not bubbled from the modal.
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-label={title}>
        <header className="modal__head">
          <div>
            <h2 className="modal__title">{title}</h2>
            {subtitle ? <p className="modal__sub">{subtitle}</p> : null}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)" }}>
            {toolbar}
            <button
              ref={closeRef}
              type="button"
              className="modal__close"
              onClick={onClose}
              aria-label="关闭"
            >
              <X size={16} />
            </button>
          </div>
        </header>
        <div className="modal__body">{children}</div>
      </div>
    </div>,
    document.body,
  );
}
