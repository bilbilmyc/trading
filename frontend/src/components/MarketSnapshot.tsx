/**
 * MarketSnapshot — the v0.4 baseline version of "top-of-page trading stats".
 *
 * Replaces 4 KPIHero tiles on TradePage with 4 hairlines + tabular numerics.
 * Differences from the older KPIHero design language:
 *   - No gradient icon chip; just an inline glyph in a 28px square.
 *   - Tabular figures everywhere (right-aligned numeric column).
 *   - 1px hairline divider between label and value, not glass.
 *   - Sparkline stays as a 90px wide SVG plot for at-a-glance shape.
 *
 * Behavior parity with KPIHero: same `label`, `value`, optional `delta`,
 * optional `sparkline`, optional `hint`. Designed to be a drop-in.
 */

import type { ReactNode } from "react";
import { Sparkline } from "./Sparkline";

type DeltaTone = "positive" | "negative" | "muted" | "warning";

const DELTA_CLASS: Record<DeltaTone, string> = {
  positive: "market-snap__delta--up",
  negative: "market-snap__delta--down",
  muted: "market-snap__delta--muted",
  warning: "market-snap__delta--muted",
};

interface MarketSnapshotProps {
  label: string;
  value: string;
  delta?: { value: string; tone?: DeltaTone };
  sparkline?: number[];
  hint?: string;
  icon?: ReactNode;
}

export function MarketSnapshot({
  label,
  value,
  delta,
  sparkline,
  hint,
  icon,
}: MarketSnapshotProps) {
  return (
    <div className="market-snap">
      <div className="market-snap__head">
        <span className="market-snap__icon" aria-hidden="true">
          {icon}
        </span>
        <span className="market-snap__label">{label}</span>
      </div>
      <div className="market-snap__value num">{value}</div>
      <div className="market-snap__foot">
        {delta ? (
          <span
            className={`market-snap__delta num ${DELTA_CLASS[delta.tone ?? "muted"]}`}
          >
            {delta.value}
          </span>
        ) : null}
        {hint ? <span className="market-snap__hint">{hint}</span> : null}
        {sparkline && sparkline.length > 1 ? (
          <span className="market-snap__sparkline">
            <Sparkline values={sparkline} />
          </span>
        ) : null}
      </div>
    </div>
  );
}
