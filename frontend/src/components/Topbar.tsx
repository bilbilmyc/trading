import { Moon, Power, Sun, Wifi, WifiOff } from "lucide-react";

import { useStatus } from "../contexts/StatusContext";
import { useTheme } from "../contexts/ThemeContext";
import { StatusPill } from "./atoms";

export function Topbar() {
  const { apiOnline, killSwitch, liveTrading, env } = useStatus();
  const { theme, toggleTheme } = useTheme();
  const liveOn = liveTrading ?? false;

  return (
    <header className="topbar topbar--secondary" aria-label="系统状态栏">
      <div className="topbar__brand">
        <span className="topbar__eyebrow">QUANT TRADER</span>
        <span className="topbar__terminal-label">EXECUTION TERMINAL</span>
      </div>
      <div className="topbar__status">
        <div className="topbar__pills" aria-label="运行状态">
          <StatusPill
            state={apiOnline ? "ok" : "bad"}
            icon={apiOnline ? <Wifi size={13} /> : <WifiOff size={13} />}
          >
            API {apiOnline ? "在线" : "离线"}
          </StatusPill>
          <StatusPill
            state={killSwitch?.enabled ? "danger" : "safe"}
            icon={<Power size={13} />}
          >
            风控 {killSwitch?.enabled ? "已触发" : "正常"}
          </StatusPill>
          <StatusPill state={liveOn ? "danger" : "neutral"}>
            {liveOn ? "实盘" : "模拟盘"}
          </StatusPill>
          <span className="topbar__env">{env}</span>
        </div>
        <button
          type="button"
          className="theme-toggle"
          onClick={toggleTheme}
          aria-label={theme === "dark" ? "切换到浅色主题" : "切换到深色主题"}
          title={theme === "dark" ? "切换到浅色主题" : "切换到深色主题"}
        >
          {theme === "dark" ? <Sun size={15} /> : <Moon size={15} />}
        </button>
      </div>
    </header>
  );
}
