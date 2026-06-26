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
import type { AppConfig, KillSwitchStatus } from "../api";

interface StatusContextValue {
  apiOnline: boolean;
  env: string;
  config: AppConfig | null;
  killSwitch: KillSwitchStatus | null;
  liveTrading: boolean;
  refresh: () => Promise<void>;
  setLiveTrading: (enabled: boolean) => void;
}

const StatusContext = createContext<StatusContextValue | null>(null);

const POLL_INTERVAL_MS = 5_000;

export function StatusProvider({ children }: { children: ReactNode }) {
  const [apiOnline, setApiOnline] = useState(false);
  const [env, setEnv] = useState("--");
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [killSwitch, setKillSwitch] = useState<KillSwitchStatus | null>(null);
  const [liveTradingEnabled, setLiveTradingEnabled] = useState(false);

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
    } catch {
      setApiOnline(false);
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  const value = useMemo<StatusContextValue>(
    () => ({
      apiOnline,
      env,
      config: config ? { ...config, live_trading_enabled: liveTradingEnabled } : null,
      killSwitch,
      liveTrading: liveTradingEnabled,
      refresh,
      setLiveTrading: setLiveTradingEnabled,
    }),
    [apiOnline, env, config, killSwitch, refresh, liveTradingEnabled]
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