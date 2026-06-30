import { Link, useLocation } from "wouter";
import {
  ArrowLeftRight,
  ClipboardList,
  Database,
  History,
  PieChart,
  Settings,
  Shield,
  Sigma,
  Star,
  TrendingUp,
} from "lucide-react";

import { useStatus } from "../contexts/StatusContext";
import { useEngine } from "../contexts/EngineContext";
import { StatusPill } from "./atoms";

interface NavItem {
  href: string;
  label: string;
  icon: typeof Database;
  description: string;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const NAV_GROUPS: NavGroup[] = [
  {
    label: "市场",
    items: [
      { href: "/markets", label: "合约行情", icon: TrendingUp, description: "K线 · MA · 成交量" },
      { href: "/watchlist", label: "自选", icon: Star, description: "多币种实时行情" },
      { href: "/data", label: "数据源", icon: Database, description: "公开行情 · 数据分析" },
    ],
  },
  {
    label: "交易",
    items: [
      { href: "/trade", label: "下单", icon: ArrowLeftRight, description: "人工下单 / 合约预览" },
      { href: "/trade-history", label: "交易历史", icon: History, description: "成交 · 盈亏 · 筛选" },
    ],
  },
  {
    label: "分析",
    items: [
      { href: "/strategies", label: "策略", icon: Sigma, description: "策略配置 · 信号流" },
      { href: "/portfolio", label: "投资组合", icon: PieChart, description: "Sharpe · Sortino · 排行榜" },
    ],
  },
  {
    label: "风控",
    items: [
      { href: "/risk", label: "风控", icon: Shield, description: "Kill switch · 风险指标" },
      { href: "/audit", label: "审计", icon: ClipboardList, description: "事件流 · 按级别过滤" },
    ],
  },
  {
    label: "系统",
    items: [
      { href: "/settings", label: "设置", icon: Settings, description: "LLM · 交易所 · 配置" },
    ],
  },
];

interface SidebarProps {
  open: boolean;
  onClose: () => void;
}

function isActive(currentPath: string, href: string): boolean {
  if (href === "/") return currentPath === "/";
  return currentPath === href || currentPath.startsWith(`${href}/`);
}

export function Sidebar({ open, onClose }: SidebarProps) {
  const [location] = useLocation();
  const { apiOnline, env, killSwitch } = useStatus();
  // Destructure both — `engineStatus` is the EngineStatus | null object,
  // `strategies` is the StrategyInfo[] (the local `engine` name conflicted
  // with EngineStatus.strategies which is string[] of exchange names).
  const { engine: engineStatus, strategies } = useEngine();
  const ordersLastMin = engineStatus?.risk?.orders_last_minute ?? 0;
  const maxOrders = engineStatus?.risk?.max_orders_per_minute ?? 100;
  const ratePct = maxOrders > 0 ? Math.min(100, (ordersLastMin / maxOrders) * 100) : 0;
  const liveCount = strategies.filter((s) => s.running).length;
  const totalStrategies = strategies.length;
  const loadPct = totalStrategies > 0 ? Math.min(100, (liveCount / totalStrategies) * 100) : 0;

  return (
    <>
      <aside className={`sidebar ${open ? "sidebar--open" : ""}`}>
        <div className="sidebar__brand" style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div
            className="gradient-brand glow"
            style={{
              width: 36,
              height: 36,
              borderRadius: 10,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              color: "#fff",
              fontSize: 18,
              fontWeight: 700,
              flexShrink: 0,
            }}
            aria-hidden="true"
          >
            ⚡
          </div>
          <div>
            <h2 className="text-gradient-brand" style={{ margin: 0, fontSize: 15 }}>
              Quant Trader
            </h2>
            <span className="sidebar__subtitle">量化交易控制台</span>
          </div>
        </div>
        <nav className="sidebar__nav">
          {NAV_GROUPS.map((group) => (
            <div key={group.label} className="sidebar__group">
              <div className="sidebar__group-label">{group.label}</div>
              {group.items.map((item) => {
                const Icon = item.icon;
                const active = isActive(location, item.href);
                return (
                  <Link
                    key={item.href}
                    href={item.href}
                    className={`sidebar__item ${active ? "is-active" : ""}`}
                    onClick={onClose}
                  >
                    <span className="sidebar__icon">
                      <Icon size={16} strokeWidth={1.75} />
                    </span>
                    <span>
                      <strong>{item.label}</strong>
                      <small>{item.description}</small>
                    </span>
                  </Link>
                );
              })}
            </div>
          ))}
        </nav>
        {/* System status card (AutoClip style: dot + 2 progress bars). */}
        <div className="sidebar__footer">
          <div className="glass-card" style={{ borderRadius: 12, padding: 10 }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                marginBottom: 8,
              }}
            >
              <span
                className="pulse-dot"
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: 3,
                  background: apiOnline ? "var(--positive)" : "var(--negative)",
                }}
                aria-hidden="true"
              />
              <span
                style={{
                  fontSize: 11,
                  color: apiOnline ? "var(--positive)" : "var(--negative)",
                  fontWeight: 500,
                }}
              >
                {apiOnline ? "System Online" : "System Offline"}
              </span>
            </div>
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <ProgressBar
                label="API Rate"
                value={`${ordersLastMin}/${maxOrders}`}
                pct={ratePct}
                gradient="linear-gradient(90deg, var(--accent) 0%, var(--accent-purple) 100%)"
              />
              <ProgressBar
                label="Runner Load"
                value={`${liveCount}/${totalStrategies}`}
                pct={loadPct}
                gradient="linear-gradient(90deg, var(--info) 0%, var(--accent) 100%)"
              />
            </div>
          </div>
        </div>
      </aside>
      {open ? <div className="sidebar__backdrop" onClick={onClose} /> : null}
    </>
  );
}

function ProgressBar({
  label,
  value,
  pct,
  gradient,
}: {
  label: string;
  value: string;
  pct: number;
  gradient: string;
}) {
  return (
    <div>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontSize: 10,
          color: "var(--text-muted)",
          marginBottom: 3,
        }}
      >
        <span>{label}</span>
        <span style={{ fontFamily: "var(--font-mono)" }}>{value}</span>
      </div>
      <div
        style={{
          width: "100%",
          height: 4,
          background: "var(--bg-elevated)",
          borderRadius: 2,
          overflow: "hidden",
        }}
      >
        <div
          style={{
            height: "100%",
            width: `${pct}%`,
            background: gradient,
            borderRadius: 2,
            transition: "width 0.4s ease",
          }}
        />
      </div>
    </div>
  );
}
