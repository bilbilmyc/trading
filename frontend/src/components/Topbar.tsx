import { Power, Wifi, WifiOff } from "lucide-react";

import { useStatus } from "../contexts/StatusContext";
import { StatusPill } from "./atoms";

export function Topbar() {
  const { apiOnline, env, killSwitch, liveTrading } = useStatus();
  // liveTrading lives in config; StatusContext exposes it via setLiveTrading state mirror.
  const liveOn = (liveTrading as unknown as boolean) ?? false;

  return (
    <header className="topbar topbar--secondary">
      <div className="topbar__status">
        <StatusPill state={apiOnline ? "ok" : "bad"} icon={apiOnline ? <Wifi size={14} /> : <WifiOff size={14} />}>
          {apiOnline ? "在线" : "离线"}
        </StatusPill>
        <StatusPill state={killSwitch?.enabled ? "danger" : "safe"} icon={<Power size={14} />}>
          KS {killSwitch?.enabled ? "ON" : "OFF"}
        </StatusPill>
        <StatusPill state={liveOn ? "danger" : "neutral"}>
          实盘 {liveOn ? "ON" : "OFF"}
        </StatusPill>
        <span className="topbar__env">{env}</span>
      </div>
    </header>
  );
}