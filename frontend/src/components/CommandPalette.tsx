/**
 * CommandPalette — global cmd+k / ctrl+k launcher.
 *
 * Two command families:
 *   1. Navigation — jump to a page (Markets / Trade / Risk / Settings …)
 *   2. Actions   — toggle live trading, toggle kill switch, refresh all
 *
 * Substring search against label + keywords, case-insensitive. Selected
 * via ↑ / ↓ / Enter; Esc closes. Empty input shows the 8 most-recent
 * commands so a fresh user has somewhere to start.
 *
 * Rendering: a single full-screen modal-overlay (not a portal) — the
 * StatusDrawer is fixed-bottom and the Spine is fixed-left, neither
 * fights with a centered dialog. Closing any of (Esc / click outside /
 * select) hides the palette.
 */

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useLocation } from "wouter";
import {
  ArrowLeftRight,
  Bot,
  ClipboardList,
  Command,
  Database,
  History,
  type LucideIcon,
  PieChart,
  Power,
  RefreshCw,
  Send,
  Settings,
  Shield,
  Sigma,
  Star,
  TrendingUp,
} from "lucide-react";

import { api } from "../api";
import { useStatus } from "../contexts/StatusContext";
import { useEngine } from "../contexts/EngineContext";

interface Command {
  id: string;
  label: string;
  hint?: string;
  group: "跳页" | "命令";
  icon: LucideIcon;
  keywords?: string[];
  run: (helpers: CommandHelpers) => void | Promise<void>;
}

interface CommandHelpers {
  navigate: (path: string) => void;
  close: () => void;
  refresh: () => Promise<void>;
  toggleLiveTrading: () => Promise<void>;
  toggleKillSwitch: () => Promise<void>;
}

const NAV_COMMANDS: Command[] = [
  { id: "nav.data",        label: "数据 / 行情",         hint: "/data",        group: "跳页", icon: Database,       keywords: ["data", "行情"], run: (h) => h.navigate("/data") },
  { id: "nav.watchlist",   label: "自选合约",           hint: "/watchlist",   group: "跳页", icon: Star,           keywords: ["watchlist", "自选"], run: (h) => h.navigate("/watchlist") },
  { id: "nav.markets",     label: "合约行情",           hint: "/markets",     group: "跳页", icon: TrendingUp,     keywords: ["markets", "k 线"], run: (h) => h.navigate("/markets") },
  { id: "nav.trade",       label: "人工下单",           hint: "/trade",       group: "跳页", icon: ArrowLeftRight, keywords: ["trade", "下单"], run: (h) => h.navigate("/trade") },
  { id: "nav.history",     label: "成交历史",           hint: "/trade-history", group: "跳页", icon: History,     keywords: ["history", "成交"], run: (h) => h.navigate("/trade-history") },
  { id: "nav.portfolio",   label: "投资组合",           hint: "/portfolio",   group: "跳页", icon: PieChart,       keywords: ["portfolio", "组合"], run: (h) => h.navigate("/portfolio") },
  { id: "nav.strategies",  label: "策略列表",           hint: "/strategies",  group: "跳页", icon: Sigma,          keywords: ["strategies", "策略"], run: (h) => h.navigate("/strategies") },
  { id: "nav.risk",        label: "风控面板",           hint: "/risk",        group: "跳页", icon: Shield,         keywords: ["risk", "风控", "kill"], run: (h) => h.navigate("/risk") },
  { id: "nav.audit",       label: "审计",               hint: "/audit",       group: "跳页", icon: ClipboardList,  keywords: ["audit", "审计"], run: (h) => h.navigate("/audit") },
  { id: "nav.events",      label: "事件时间线",         hint: "/events",      group: "跳页", icon: History,        keywords: ["events", "时间线"], run: (h) => h.navigate("/events") },
  { id: "nav.bot",         label: "Bot 监控",           hint: "/bot",         group: "跳页", icon: Send,           keywords: ["bot", "telegram"], run: (h) => h.navigate("/bot") },
  { id: "nav.settings",    label: "设置",               hint: "/settings",    group: "跳页", icon: Settings,       keywords: ["settings", "设置", "配置"], run: (h) => h.navigate("/settings") },
];

function ActionCommand(args: {
  id: string;
  label: string;
  hint?: string;
  icon: LucideIcon;
  keywords?: string[];
  run: (h: CommandHelpers) => void | Promise<void>;
}): Command {
  return { group: "命令", ...args };
}

const ALL_COMMANDS: Command[] = NAV_COMMANDS; // action commands built at render time

function score(cmd: Command, q: string): number {
  if (!q) return 1;
  const needle = q.toLowerCase();
  const hay = [cmd.label, cmd.hint ?? "", ...(cmd.keywords ?? [])]
    .join(" ")
    .toLowerCase();
  if (hay.includes(needle)) return 2;
  // Subsequence match — "ms" matches "markets".
  let i = 0;
  for (const ch of hay) {
    if (ch === needle[i]) i += 1;
    if (i === needle.length) return 1;
  }
  return 0;
}

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const [, navigate] = useLocation();
  const inputRef = useRef<HTMLInputElement>(null);
  const { refresh: refreshStatus, killSwitch, setLiveTrading, config } = useStatus();
  const { refresh: refreshEngine } = useEngine();

  // Global hotkey: ⌘K / Ctrl+K toggles the palette. Esc inside the
  // palette closes it. Listener attached to document so it works
  // regardless of focus.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const modK = (e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k";
      if (modK) {
        e.preventDefault();
        setOpen((v) => !v);
      } else if (e.key === "Escape" && open) {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open]);

  // Reset state every time the palette opens.
  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      // Defer focus to next tick — the input is already mounted.
      window.setTimeout(() => inputRef.current?.focus(), 0);
    }
  }, [open]);

  // Action commands are built at render time because they need the
  // current `killSwitch` / `liveTrading` flags to render their hint.
  const commands: Command[] = useMemo(() => {
    const refresh: Command = ActionCommand({
      id: "act.refresh",
      label: "刷新全部状态",
      hint: "API + config + engine",
      icon: RefreshCw,
      keywords: ["refresh", "刷新"],
      run: async (h) => {
        await Promise.all([refreshStatus(), refreshEngine()]);
        h.close();
      },
    });
    const toggleLive: Command = ActionCommand({
      id: "act.toggle-live",
      label: config?.live_trading_enabled ? "关闭实盘交易" : "开启实盘交易",
      hint: "live_trading_enabled",
      icon: Power,
      keywords: ["live", "实盘", "toggle"],
      run: async (h) => {
        const next = !config?.live_trading_enabled;
        if (next && !window.confirm("开启实盘？所有实盘下单、风控将被激活。")) {
          h.close();
          return;
        }
        await api.toggleLiveTrading(next);
        setLiveTrading(next);
        await refreshStatus();
        h.close();
      },
    });
    const toggleKs: Command = ActionCommand({
      id: "act.toggle-ks",
      label: killSwitch?.enabled ? "解除 Kill Switch" : "触发 Kill Switch",
      hint: "全局熔断",
      icon: Shield,
      keywords: ["kill", "熔断", "kill switch"],
      run: async (h) => {
        const next = !killSwitch?.enabled;
        if (next && !window.confirm("确认开启全局 Kill Switch？")) {
          h.close();
          return;
        }
        await api.setKillSwitch(next, "command_palette");
        await Promise.all([refreshStatus(), refreshEngine()]);
        h.close();
      },
    });
    return [refresh, toggleLive, toggleKs, ...ALL_COMMANDS];
  }, [config?.live_trading_enabled, killSwitch?.enabled, refreshStatus, refreshEngine, setLiveTrading]);

  const filtered = useMemo(() => {
    const q = query.trim();
    if (!q) return commands;
    return commands.filter((c) => score(c, q) > 0);
  }, [commands, query]);

  // Keep cursor inside the filtered window as the user types.
  useEffect(() => {
    if (cursor >= filtered.length) setCursor(0);
  }, [filtered, cursor]);

  const helpers: CommandHelpers = {
    navigate: (p) => {
      navigate(p);
      setOpen(false);
    },
    close: () => setOpen(false),
    refresh: async () => {
      await Promise.all([refreshStatus(), refreshEngine()]);
    },
    toggleLiveTrading: async () => {
      const next = !config?.live_trading_enabled;
      if (next && !window.confirm("开启实盘？")) return;
      await api.toggleLiveTrading(next);
      setLiveTrading(next);
    },
    toggleKillSwitch: async () => {
      const next = !killSwitch?.enabled;
      if (next && !window.confirm("确认触发 Kill Switch？")) return;
      await api.setKillSwitch(next, "command_palette");
    },
  };

  if (!open) return null;

  const onSelect = (cmd: Command) => {
    void cmd.run(helpers);
  };

  return (
    <div
      className="cmd-palette"
      role="dialog"
      aria-label="命令面板"
      onClick={() => setOpen(false)}
    >
      <div
        className="cmd-palette__panel"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="cmd-palette__head">
          <Command size={14} className="cmd-palette__icon" aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            className="cmd-palette__input"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") {
                e.preventDefault();
                setCursor((c) => (filtered.length === 0 ? 0 : (c + 1) % filtered.length));
              } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setCursor((c) => (filtered.length === 0 ? 0 : (c - 1 + filtered.length) % filtered.length));
              } else if (e.key === "Enter") {
                e.preventDefault();
                const cmd = filtered[cursor];
                if (cmd) onSelect(cmd);
              }
            }}
            placeholder="输入命令或页面名（⌘K）"
            autoComplete="off"
            spellCheck={false}
          />
          <span className="cmd-palette__hint">esc</span>
        </div>
        <div className="cmd-palette__list">
          {filtered.length === 0 ? (
            <div className="cmd-palette__empty">无匹配命令</div>
          ) : (
            filtered.map((cmd, i) => (
              <Row
                key={cmd.id}
                cmd={cmd}
                active={i === cursor}
                onMouseEnter={() => setCursor(i)}
                onClick={() => onSelect(cmd)}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function Row({
  cmd,
  active,
  onClick,
  onMouseEnter,
}: {
  cmd: Command;
  active: boolean;
  onClick: () => void;
  onMouseEnter: () => void;
}): ReactNode {
  const Icon = cmd.icon;
  return (
    <button
      type="button"
      className={`cmd-palette__row ${active ? "cmd-palette__row--active" : ""}`}
      onClick={onClick}
      onMouseEnter={onMouseEnter}
    >
      <Icon size={14} className="cmd-palette__row-icon" aria-hidden="true" />
      <span className="cmd-palette__row-label">{cmd.label}</span>
      <span className="cmd-palette__row-group">{cmd.group}</span>
      {cmd.hint ? <span className="cmd-palette__row-hint">{cmd.hint}</span> : null}
    </button>
  );
}
