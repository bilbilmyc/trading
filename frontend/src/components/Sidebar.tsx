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
    label: "数据",
    items: [
      { href: "/data", label: "数据源", icon: Database, description: "公开行情 · 数据分析" },
      { href: "/watchlist", label: "自选", icon: Star, description: "多币种实时行情" },
      { href: "/markets", label: "行情", icon: TrendingUp, description: "K线 · MA · 成交量" },
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

  return (
    <>
      <aside className={`sidebar ${open ? "sidebar--open" : ""}`}>
        <div className="sidebar__brand">
          <h2>Quant Trader</h2>
          <span className="sidebar__subtitle">量化交易控制台</span>
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
          <StatusPill state={apiOnline ? "ok" : "bad"}>
            后端 {apiOnline ? "在线" : "离线"}
          </StatusPill>
          <StatusPill state={killSwitch?.enabled ? "danger" : "safe"}>
            KS {killSwitch?.enabled ? "ON" : "OFF"}
          </StatusPill>
          <span className="sidebar__env">{env}</span>
        </div>
      </aside>
      {open ? <div className="sidebar__backdrop" onClick={onClose} /> : null}
    </>
  );
}
