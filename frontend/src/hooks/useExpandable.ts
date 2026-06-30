import { useCallback, useState } from "react";

/**
 * Tiny open/close state helper used by pages that mount an `<ExpandModal>`
 * to show their full un-capped data set.
 *
 *   const all = useExpandable();
 *   <ExpandModal isOpen={all.isOpen} onClose={all.close} ... />
 *   <button onClick={all.open}>展开全部</button>
 */
export function useExpandable(initial = false) {
  const [isOpen, setOpen] = useState(initial);
  const open = useCallback(() => setOpen(true), []);
  const close = useCallback(() => setOpen(false), []);
  const toggle = useCallback(() => setOpen((v) => !v), []);
  return { isOpen, open, close, toggle };
}
