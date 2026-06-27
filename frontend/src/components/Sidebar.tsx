import { Link, useLocation } from "wouter";
import type { ReactNode } from "react";

import { useStatus } from "../contexts/StatusContext";
import { StatusPill } from "./atoms";

interface NavItem {
  href: string;
  label: string;
  icon: ReactNode;
  description: string;
}

const NAV_ITEMS: NavItem[] = [
  { href: "/data", label: "数据源", icon: "≣", description: "公开行情 · 数据分析" },
  { href: "/portfolio", label: "投资组合", icon: "∑", description: "Sharpe · Sortino · 排行榜" },
  { href: "/markets", label: "行情", icon: "↗", description: "Ticker · 成交 · 挂单" },
  { href: "/trade", label: "下单单", icon: "→", description: "人工下单 / 合约预览" },
  { href: "/strategies", label: "策略", icon: "◊", description: "策略配置 · 信号流" },
  { href: "/risk", label: "风控", icon: "!", description: "Kill switch · 风险指标" },
  { href: "/audit", label: "审计", icon: "≡", description: "事件流 · 按级别过滤" },
  { href: "/settings", label: "设置", icon: "⚙", description: "LLM · 交易所 · 配置" },
];

interface SidebarProps {
  open: boolean;
  onClose: () => void;
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
          {NAV_ITEMS.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={`sidebar__item ${location === item.href ? "is-active" : ""}`}
              onClick={onClose}
            >
              <span className="sidebar__icon">{item.icon}</span>
              <span>
                <strong>{item.label}</strong>
                <small>{item.description}</small>
              </span>
            </Link>
          ))}
        </nav>
        <div className="sidebar__footer">
          <StatusPill state={apiOnline ? "ok" : "bad"}>
            后端 {apiOnline ? "在线" : "离线"}
          </StatusPill>
          <StatusPill
            state={killSwitch?.enabled ? "danger" : "safe"}
          >
            KS {killSwitch?.enabled ? "ON" : "OFF"}
          </StatusPill>
          <span className="sidebar__env">{env}</span>
        </div>
      </aside>
      {open && <div className="sidebar__backdrop" onClick={onClose} />}
    </>
  );
}