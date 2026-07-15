import { useEffect, useState } from "react";

import { useStatus } from "../contexts/StatusContext";
import { useEngine } from "../contexts/EngineContext";

/**
 * Bloomberg-style status strip rendered under the Topbar. Shows live engine
 * status, kill-switch state, paper/live mode, and a ticking UTC clock. All
 * values are mono-spaced and tabular-num aligned for at-a-glance scanning.
 *
 * Signature element of the trading console — gives the page the "pro trading
 * terminal" feel rather than a generic admin template.
 */
export function StatusTicker() {
  const { apiOnline, killSwitch, liveTrading, env } = useStatus();
  const { engine } = useEngine();
  const [now, setNow] = useState(() => new Date());

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const utc = now.toISOString().slice(11, 19);
  const date = now.toISOString().slice(0, 10);
  const local = now.toLocaleTimeString();
  const runnerRunning = engine?.signal_runner?.running ?? false;
  const paper = engine?.paper?.equity;
  const ordersLastMin = engine?.risk?.orders_last_minute ?? 0;
  const maxOrders = engine?.risk?.max_orders_per_minute ?? 0;

  return (
    <div className="status-ticker" role="status" aria-label="Engine status">
      <span className="status-ticker__cell">
        <span className="status-ticker__pulse" aria-hidden="true" />
        <span className={apiOnline ? "status-ticker__cell--pos" : "status-ticker__cell--neg"}>
          {apiOnline ? "API ONLINE" : "API OFFLINE"}
        </span>
      </span>

      <span className="status-ticker__cell">
        <span className="status-ticker__label">KS</span>
        <span className={killSwitch?.enabled ? "status-ticker__cell--neg" : "status-ticker__cell--pos"}>
          {killSwitch?.enabled ? "TRIPPED" : "ARMED"}
        </span>
      </span>

      <span className="status-ticker__cell">
        <span className="status-ticker__label">MODE</span>
        <span className={liveTrading ? "status-ticker__cell--neg" : "status-ticker__cell--muted"}>
          {liveTrading ? "LIVE" : "PAPER"}
        </span>
      </span>

      <span className="status-ticker__cell">
        <span className="status-ticker__label">RUNNER</span>
        <span className={runnerRunning ? "status-ticker__cell--pos" : "status-ticker__cell--muted"}>
          {runnerRunning ? "ON" : "OFF"}
        </span>
      </span>

      <span className="status-ticker__cell">
        <span className="status-ticker__label">RATE</span>
        <span>
          {ordersLastMin}/{maxOrders}/min
        </span>
      </span>

      {paper !== undefined ? (
        <span className="status-ticker__cell">
          <span className="status-ticker__label">PAPER</span>
          <span className="data-mono">${paper.toFixed(2)}</span>
        </span>
      ) : null}

      <span className="status-ticker__cell status-ticker__cell--clock">
        <span className="status-ticker__label">UTC</span>
        <span className="data-mono">{utc}</span>
        <span className="status-ticker__label status-ticker__label--local">LOCAL</span>
        <span className="data-mono">{local}</span>
      </span>

      <span className="status-ticker__cell status-ticker__cell--muted">{env}</span>
    </div>
  );
}
