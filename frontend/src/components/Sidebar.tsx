import { Link, useLocation } from "wouter";
import {
  ArrowLeftRight,
  ClipboardList,
  Database,
  History,
  MessageSquare,
  PieChart,
  Send,
  Settings,
  Shield,
  Sigma,
  Star,
  TrendingUp,
  Zap,
} from "lucide-react";

import { useStatus } from "../contexts/StatusContext";
import { useEngine } from "../contexts/EngineContext";
import { ProgressBar } from "./ProgressBar";
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
      { href: "/events", label: "事件时间线", icon: History, description: "60 分钟历史 · 分类筛选" },
      { href: "/bot", label: "Bot 监控", icon: Send, description: "Telegram bot · 命令速查 · 静默" },
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
  const { apiOnline, killSwitch } = useStatus();
  const { engine, strategies } = useEngine();

  // Note: `engine` IS the status object (not array of strategies). The
  // local variable name comes from useEngine's bundle alias to avoid
  // colliding with `engineStatus.strategies` (which is a string[] of
  // exchange names downstream code might expect).
  const ordersLastMin = engine?.risk?.orders_last_minute ?? 0;
  const maxOrders = engine?.risk?.max_orders_per_minute ?? 100;
  const ratePct = maxOrders > 0 ? Math.min(100, (ordersLastMin / maxOrders) * 100) : 0;
  const liveCount = strategies.filter((s) => s.running).length;
  const totalStrategies = strategies.length;
  const loadPct =
    totalStrategies > 0 ? Math.min(100, (liveCount / totalStrategies) * 100) : 0;

  return (
    <>
      <aside className={`sidebar ${open ? "sidebar--open" : ""}`}>
        <div className="sidebar__brand">
          <div className="brand-mark gradient-brand glow" aria-hidden="true">
            <Zap size={18} strokeWidth={2.25} />
          </div>
          <div>
            <h2 className="text-gradient-brand sidebar__title">Quant Trader</h2>
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
        <div className="sidebar__footer">
          <div className="sidebar__status-card">
            <div className="sidebar__status-head">
              <span
                className={`sidebar__pulse ${apiOnline ? "sidebar__pulse--ok" : "sidebar__pulse--bad"}`}
                aria-hidden="true"
              />
              <span
                className={`sidebar__status-text ${apiOnline ? "sidebar__status-text--ok" : "sidebar__status-text--bad"}`}
              >
                {apiOnline ? "System Online" : "System Offline"}
              </span>
              {killSwitch?.enabled ? (
                <StatusPill state="danger">
                  <MessageSquare size={11} /> KS
                </StatusPill>
              ) : null}
            </div>
            <ProgressBar
              label="API Rate"
              value={`${ordersLastMin}/${maxOrders}`}
              pct={ratePct}
            />
            <ProgressBar
              label="Runner Load"
              value={`${liveCount}/${totalStrategies}`}
              pct={loadPct}
              gradient="linear-gradient(90deg, var(--info) 0%, var(--accent) 100%)"
            />
          </div>
        </div>
      </aside>
      {open ? <div className="sidebar__backdrop" onClick={onClose} /> : null}
    </>
  );
}
