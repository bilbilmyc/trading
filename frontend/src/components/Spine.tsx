/**
 * The Spine — 4px vertical status strip (signature element).
 *
 * Encoded signals (top → bottom):
 *   1. API online              (green / red + pulse)
 *   2. Live trading            (neutral / red)
 *   3. Kill switch             (gray / red)
 *   4. Bot status              (gray / cyan / warning+ping if alerting)
 *   5. Drawdown segment        (green→yellow→red gradient by depth)
 *
 * Each segment reveals a one-line tooltip on hover so the Spine never
 * needs to take screen real-estate to explain itself.
 *
 * Segment 4 reflects `engine.bot.enabled` directly. When the bot is
 * unconfigured it stays dark/gray; while the bot is configured but the
 * monitor reports at least one error-level event, the segment pulses
 * amber to attract attention.
 */

import { useEngine } from "../contexts/EngineContext";
import { useStatus } from "../contexts/StatusContext";

function drawdownClass(value: number): string {
  if (value >= 0.15) return "spine__seg--dd-high";
  if (value >= 0.08) return "spine__seg--dd-medium";
  return "spine__seg--dd-low";
}

function fmtPct(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

export function Spine() {
  const { apiOnline, killSwitch, liveTrading } = useStatus();
  const { engine, events } = useEngine();

  const drawdown = engine?.risk?.current_drawdown ?? 0;
  const botEnabled = engine?.bot?.enabled ?? false;
  const botAlerting = events.some(
    (e) => e.level === "critical" || e.level === "error",
  );
  const botClass = !botEnabled
    ? "spine__seg--bot-disabled"
    : botAlerting
      ? "spine__seg--bot-alerting"
      : "spine__seg--bot-enabled";

  const botTip = !botEnabled
    ? "Bot: disabled"
    : botAlerting
      ? "Bot: alerting"
      : "Bot: online";

  return (
    <aside className="spine" aria-label="system status">
      <div
        className={`spine__seg ${apiOnline ? "spine__seg--api-ok" : "spine__seg--api-bad"}`}
        data-tip={`API: ${apiOnline ? "online" : "OFFLINE"}`}
      />
      <div
        className={`spine__seg ${liveTrading ? "spine__seg--live-on" : "spine__seg--live-off"}`}
        data-tip={`Live trading: ${liveTrading ? "ON" : "off"}`}
      />
      <div
        className={`spine__seg ${killSwitch?.enabled ? "spine__seg--ks-on" : "spine__seg--ks-off"}`}
        data-tip={`Kill switch: ${killSwitch?.enabled ? "TRIPPED" : "armed"}`}
      />
      <div
        className={`spine__seg ${botClass}`}
        data-tip={botTip}
      />
      <div
        className={`spine__seg ${drawdownClass(drawdown)}`}
        data-tip={`Drawdown: ${fmtPct(drawdown)}`}
      />
    </aside>
  );
}
