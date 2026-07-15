import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { api } from "../api";
import type { AppConfig, KillSwitchStatus } from "../api";

interface StatusContextValue {
  apiOnline: boolean;
  env: string;
  config: AppConfig | null;
  killSwitch: KillSwitchStatus | null;
  liveTrading: boolean;
  /** ms-since-epoch of the most recent successful `refresh()` call. */
  lastRefreshedAt: number | null;
  refresh: () => Promise<void>;
  setLiveTrading: (enabled: boolean) => void;
}

const StatusContext = createContext<StatusContextValue | null>(null);

// Polling remains as a fallback in case SSE is blocked (proxies, dev tools).
const POLL_INTERVAL_MS = 15_000;

export function StatusProvider({ children }: { children: ReactNode }) {
  const [apiOnline, setApiOnline] = useState(false);
  const [env, setEnv] = useState("--");
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [killSwitch, setKillSwitch] = useState<KillSwitchStatus | null>(null);
  const [liveTradingEnabled, setLiveTradingEnabled] = useState(false);
  const [lastRefreshedAt, setLastRefreshedAt] = useState<number | null>(null);
  const esRef = useRef<EventSource | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [health, runtimeConfig, kill] = await Promise.all([
        api.health(),
        api.config(),
        api.killSwitchStatus(),
      ]);
      setApiOnline(health.status === "ok");
      setEnv(health.env);
      setConfig(runtimeConfig);
      setLiveTradingEnabled(Boolean(runtimeConfig.live_trading_enabled));
      setKillSwitch(kill);
      setLastRefreshedAt(Date.now());
    } catch {
      setApiOnline(false);
    }
  }, []);

  // Subscribe to SSE for server-pushed updates. EventSource auto-reconnects
  // on transient failures; polling remains as a long-interval fallback.
  useEffect(() => {
    const es = new EventSource("/api/v1/stream/events?heartbeat_seconds=10");
    esRef.current = es;
    es.onmessage = () => {
      // Any server event means state may have changed.
      void refresh();
    };
    es.onerror = () => {
      // EventSource will auto-reconnect; mark offline only when readyState is CLOSED.
      if (es.readyState === EventSource.CLOSED) {
        setApiOnline(false);
      }
    };

    void refresh();
    const id = window.setInterval(refresh, POLL_INTERVAL_MS);

    return () => {
      window.clearInterval(id);
      es.close();
      esRef.current = null;
    };
  }, [refresh]);

  const value = useMemo<StatusContextValue>(
    () => ({
      apiOnline,
      env,
      config: config ? { ...config, live_trading_enabled: liveTradingEnabled } : null,
      killSwitch,
      liveTrading: liveTradingEnabled,
      lastRefreshedAt,
      refresh,
      setLiveTrading: setLiveTradingEnabled,
    }),
    [apiOnline, env, config, killSwitch, refresh, liveTradingEnabled, lastRefreshedAt]
  );

  return <StatusContext.Provider value={value}>{children}</StatusContext.Provider>;
}

export function useStatus(): StatusContextValue {
  const ctx = useContext(StatusContext);
  if (ctx === null) {
    throw new Error("useStatus must be used inside <StatusProvider>");
  }
  return ctx;
}