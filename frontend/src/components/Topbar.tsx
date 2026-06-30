import { Moon, Power, Sun, Wifi, WifiOff } from "lucide-react";

import { useStatus } from "../contexts/StatusContext";
import { useTheme } from "../contexts/ThemeContext";
import { StatusPill } from "./atoms";

export function Topbar() {
  const { apiOnline, killSwitch, liveTrading, env } = useStatus();
  const { theme, toggleTheme } = useTheme();
  const liveOn = liveTrading ?? false;

  return (
    <header className="topbar topbar--secondary glass">
      <div className="topbar__brand" style={{ display: "flex", alignItems: "center", gap: 12 }}>
        {/* Brand mark: gradient indigo→purple bolt inside a rounded square. */}
        <div
          className="gradient-brand glow"
          style={{
            width: 40,
            height: 40,
            borderRadius: 12,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            color: "#fff",
            fontWeight: 700,
            fontSize: 18,
          }}
          aria-hidden="true"
        >
          ⚡
        </div>
        <div>
          <div
            className="eyebrow"
            style={{ color: "var(--text-muted)", letterSpacing: "0.18em" }}
          >
            Quant Trader
          </div>
          <h1
            className="text-gradient-brand"
            style={{ margin: "2px 0 0", fontSize: 20, fontWeight: 700, lineHeight: 1.1 }}
          >
            量化交易控制台
          </h1>
          <span className="topbar__subtitle">
            实时行情 · 策略信号 · 风险监控
          </span>
        </div>
      </div>
      <div className="topbar__status">
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
