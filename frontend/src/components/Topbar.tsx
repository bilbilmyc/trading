import { Moon, Power, Sun, Wifi, WifiOff, Zap } from "lucide-react";

import { useStatus } from "../contexts/StatusContext";
import { useTheme } from "../contexts/ThemeContext";
import { StatusPill } from "./atoms";

export function Topbar() {
  const { apiOnline, killSwitch, liveTrading, env } = useStatus();
  const { theme, toggleTheme } = useTheme();
  const liveOn = liveTrading ?? false;

  return (
    <header className="topbar topbar--secondary glass">
      <div className="topbar__brand">
        <div className="brand-mark gradient-brand glow topbar__brand-mark" aria-hidden="true">
          <Zap size={20} strokeWidth={2.25} />
        </div>
        <div>
          <div className="eyebrow topbar__eyebrow">Quant Trader</div>
          <h1 className="text-gradient-brand topbar__title">量化交易控制台</h1>
          <span className="topbar__subtitle">
            实时行情 · 策略信号 · 风险监控
          </span>
        </div>
      </div>
      <div className="topbar__status">
        <div className="topbar__pills">
          <StatusPill
            state={apiOnline ? "ok" : "bad"}
            icon={apiOnline ? <Wifi size={14} /> : <WifiOff size={14} />}
          >
            {apiOnline ? "在线" : "离线"}
          </StatusPill>
          <StatusPill
            state={killSwitch?.enabled ? "danger" : "safe"}
            icon={<Power size={14} />}
          >
            KS {killSwitch?.enabled ? "ON" : "OFF"}
          </StatusPill>
          <StatusPill state={liveOn ? "danger" : "neutral"}>
            实盘 {liveOn ? "ON" : "OFF"}
          </StatusPill>
          <span className="topbar__env">{env}</span>
        </div>
        {/* Theme toggle lives outside the pill group so it always
            stays pinned to the right edge even when pills wrap. */}
        <button
          type="button"
          className="theme-toggle"
          onClick={toggleTheme}
          aria-label={theme === "dark" ? "切换到浅色主题" : "切换到深色主题"}
          title={theme === "dark" ? "切换到浅色主题" : "切换到深色主题"}
        >
          {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>
      </div>
    </header>
  );
}
