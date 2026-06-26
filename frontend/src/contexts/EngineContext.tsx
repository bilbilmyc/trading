import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { api } from "../api";
import type {
  AuditEvent,
  EngineStatus,
  PaperSummary,
  StrategyInfo,
  StrategySignal,
} from "../api";

interface EngineContextValue {
  engine: EngineStatus | null;
  strategies: StrategyInfo[];
  signals: StrategySignal[];
  events: AuditEvent[];
  paper: PaperSummary | null;
  refresh: () => Promise<void>;
}

const EngineContext = createContext<EngineContextValue | null>(null);

const POLL_INTERVAL_MS = 5_000;

export function EngineProvider({ children }: { children: ReactNode }) {
  const [engine, setEngine] = useState<EngineStatus | null>(null);
  const [strategies, setStrategies] = useState<StrategyInfo[]>([]);
  const [signals, setSignals] = useState<StrategySignal[]>([]);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [paper, setPaper] = useState<PaperSummary | null>(null);

  const refresh = useCallback(async () => {
    if (engine === null) {
      // First load — fetch all in parallel.
      try {
        const [status, s, sig, ev, p] = await Promise.all([
          api.engineStatus(),
          api.strategies(),
          api.recentSignals(10),
          api.recentEvents(12),
          api.paper(),
        ]);
        setEngine(status);
        setStrategies(s.strategies);
        setSignals(sig.signals);
        setEvents(ev.events);
        setPaper(p);
      } catch {
        // status will retry on next tick
      }
    } else {
      try {
        const status = await api.engineStatus();
        setEngine(status);
      } catch {
        // ignore — keep last good snapshot
      }
    }
  }, [engine]);

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  const value = useMemo<EngineContextValue>(
    () => ({ engine, strategies, signals, events, paper, refresh }),
    [engine, strategies, signals, events, paper, refresh]
  );

  return <EngineContext.Provider value={value}>{children}</EngineContext.Provider>;
}

export function useEngine(): EngineContextValue {
  const ctx = useContext(EngineContext);
  if (ctx === null) {
    throw new Error("useEngine must be used inside <EngineProvider>");
  }
  return ctx;
}