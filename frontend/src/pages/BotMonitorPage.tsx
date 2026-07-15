/**
 * Bot monitor page — operational overview for the Telegram notification bot.
 *
 * Data sources:
 *   - engine.bot (BotStatus, populated by /api/v1/engine/status.bot)
 *   - killSwitch (from StatusContext)
 *   - /api/v1/risk/kill-switch POST for the quick-toggle.
 */

import { useEffect, useMemo, useState } from "react";
import {
  Bell,
  Bot,
  CheckCircle2,
  Clock3,
  MessageCircle,
  Send,
  ShieldAlert,
  Terminal,
  Users,
} from "lucide-react";

import { useEngine } from "../contexts/EngineContext";
import { useStatus } from "../contexts/StatusContext";
import { api } from "../api";
import { Card } from "../components/Card";
import { EmptyState, StatusPill } from "../components/atoms";
import { KPIHero } from "../components/KPIHero";
import { PageHeader } from "../components/PageHeader";
import { SectionPanel } from "../components/SectionPanel";

const COMMAND_CATALOG: Array<{
  cmd: string;
  category: string;
  brief: string;
}> = [
  { cmd: "/help", category: "查询", brief: "列出所有可用命令" },
  { cmd: "/status", category: "查询", brief: "引擎运行状态总览" },
  { cmd: "/pnl", category: "查询", brief: "模拟盘资金 / 已实现 / 未实现" },
  { cmd: "/positions", category: "查询", brief: "当前持仓明细" },
  { cmd: "/signals", category: "查询", brief: "最近 5 条策略信号" },
  { cmd: "/strategies", category: "查询", brief: "策略列表 + 运行状态" },
  { cmd: "/risk", category: "查询", brief: "风控阈值实时状态" },
  { cmd: "/events", category: "查询", brief: "最近 8 条审计事件" },
  { cmd: "/ticker SYMBOL", category: "查询", brief: "查行情（默认 BTCUSDT）" },
  { cmd: "/runner", category: "查询", brief: "信号运行器周期数 / 最近错误" },
  { cmd: "/kill on [reason]", category: "操作", brief: "启用 kill switch" },
  { cmd: "/kill off [reason]", category: "操作", brief: "关闭 kill switch" },
  { cmd: "/start_strategy NAME", category: "操作", brief: "启用策略" },
  { cmd: "/stop_strategy NAME", category: "操作", brief: "停用策略" },
];

function fmtHour(h: number): string {
  return `${h.toString().padStart(2, "0")}:00`;
}

export function BotMonitorPage() {
  const { engine, refresh } = useEngine();
  const { killSwitch, lastRefreshedAt } = useStatus();
  const [flipPending, setFlipPending] = useState(false);
  const [flipError, setFlipError] = useState<string | null>(null);

  // Pull the bot status eagerly if the engine bootstrap hasn't surfaced
  // it (older servers don't include the augmentation, so we always try).
  useEffect(() => {
    if (engine?.bot === undefined) {
      void api.botStatus().catch(() => null);
    }
  }, [engine?.bot]);

  const bot = engine?.bot;
  const botEnabled = bot?.enabled ?? false;
  const botChats: number[] = bot?.allowed_chat_ids ?? [];
  const tokenTail = bot?.token_tail ?? "—";
  const quietHours: [number, number] | null = bot?.quiet_hours ?? null;
  const quietPercent = useMemo(() => {
    if (!quietHours) return 0;
    const [start, end] = quietHours;
    const span = start <= end ? end - start : 24 - start + end;
    return (span / 24) * 100;
  }, [quietHours]);

  const currentHour = new Date().getHours();
  const inQuietNow = useMemo(() => {
    if (!quietHours) return false;
    const [start, end] = quietHours;
    if (start <= end) return currentHour >= start && currentHour < end;
    return currentHour >= start || currentHour < end;
  }, [quietHours, currentHour]);

  async function toggleKill() {
    setFlipPending(true);
    setFlipError(null);
    try {
      const enabled = !killSwitch?.enabled;
      await api.setKillSwitch(enabled, "bot_monitor_page");
      await refresh();
    } catch (err) {
      setFlipError((err as Error).message);
    } finally {
      setFlipPending(false);
    }
  }

  return (
    <div className="page page--bot stack">
      <PageHeader
        icon={<Bot size={18} />}
        eyebrow="自动化 / BOT"
        title="Bot 监控"
        subtitle="Telegram 告警通道 · 命令能力 · 静默策略 · Kill Switch"
        freshness={lastRefreshedAt ? { at: lastRefreshedAt } : null}
      />

      <div className="kpi-strip kpi-strip--four">
        <KPIHero
          label="运行状态"
          value={botEnabled ? "已启用" : "未启用"}
          icon={<Bot size={13} />}
          iconGradient={botEnabled ? "green" : "indigo"}
          delta={{ value: botEnabled ? "ONLINE" : "OFFLINE", tone: botEnabled ? "positive" : "muted" }}
          hint="Telegram bot"
        />
        <KPIHero
          label="允许 chat"
          value={botChats.length > 0 ? String(botChats.length) : "全部"}
          icon={<Users size={13} />}
          iconGradient="cyan"
          delta={{ value: botChats.length > 0 ? "白名单" : "开放", tone: "muted" }}
          hint={botChats.length > 0 ? "个 chat" : "未限制"}
        />
        <KPIHero
          label="最低告警级别"
          value={bot?.min_alert_level ?? "warning"}
          icon={<Bell size={13} />}
          iconGradient="yellow"
          hint="由 bot 推送"
        />
        <KPIHero
          label="静默策略"
          value={quietHours ? "已配置" : "始终推送"}
          icon={<Clock3 size={13} />}
          iconGradient={quietHours ? "orange" : "indigo"}
          hint={quietHours ? `${fmtHour(quietHours[0])} – ${fmtHour(quietHours[1])}` : "无静默时段"}
        />
      </div>

      <div className="page__grid page__grid--split bot-monitor-grid">
        <SectionPanel
          className="bot-command-panel"
          title={
            <span className="bot-panel-title">
              <Terminal size={13} /> 命令速查
            </span>
          }
          trailing={<span className="badge badge--cyan">{COMMAND_CATALOG.length} COMMANDS</span>}
        >
          <table className="bot-cmd-table">
            <thead>
              <tr>
                <th>命令</th>
                <th>分类</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              {COMMAND_CATALOG.map((command) => (
                <tr key={command.cmd}>
                  <td><code>{command.cmd}</code></td>
                  <td><span className={`bot-command-category bot-command-category--${command.category === "操作" ? "action" : "query"}`}>{command.category}</span></td>
                  <td>{command.brief}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="page__note bot-command-note">
            命令由 <code>app/bot/commands.py</code> 处理，并通过引擎状态与风险端点执行查询或操作。
          </p>
        </SectionPanel>

        <div className="stack stack--tight">
          <Card
            title="Bot 状态"
            subtitle="连接与权限摘要"
            trailing={
              <StatusPill state={botEnabled ? "ok" : "neutral"} icon={<Bot size={13} />}>
                {botEnabled ? "ONLINE" : "OFFLINE"}
              </StatusPill>
            }
          >
            <div className="bot-status-list">
              <div className="kv-row">
                <span className="kv-row__label"><MessageCircle size={12} /> Token 后 4 位</span>
                <span className="kv-row__value num">{tokenTail || "—"}</span>
              </div>
              <div className="kv-row">
                <span className="kv-row__label"><Users size={12} /> 允许 chat</span>
                <span className="kv-row__value num">{botChats.length > 0 ? botChats.length : "全部（开放）"}</span>
              </div>
              <div className="kv-row">
                <span className="kv-row__label"><Bell size={12} /> 最小告警级别</span>
                <span className="kv-row__value num">{bot?.min_alert_level ?? "warning"}</span>
              </div>
            </div>
          </Card>

          <Card
            title="Kill Switch"
            subtitle="与 bot 端 /kill on|off 共用同一风险端点"
            trailing={
              <StatusPill state={killSwitch?.enabled ? "danger" : "safe"} icon={<ShieldAlert size={13} />}>
                {killSwitch?.enabled ? "ARMED" : "CLEAR"}
              </StatusPill>
            }
            className={killSwitch?.enabled ? "bot-kill-card bot-kill-card--armed" : "bot-kill-card"}
          >
            <div className="bot-kill-action">
              <div>
                <strong>{killSwitch?.enabled ? "交易保护已启用" : "交易保护未启用"}</strong>
                <p>{killSwitch?.enabled ? "新订单会被风险层拦截。" : "需要时可从这里快速启用。"}</p>
              </div>
              <button
                type="button"
                className={`action ${killSwitch?.enabled ? "action--safe" : "action--danger"}`}
                onClick={toggleKill}
                disabled={flipPending}
              >
                {killSwitch?.enabled ? <CheckCircle2 size={15} /> : <ShieldAlert size={15} />}
                {flipPending ? "处理中…" : killSwitch?.enabled ? "关闭" : "启用"}
              </button>
            </div>
            {flipError ? <p className="bot-hint bot-hint--err">{flipError}</p> : null}
          </Card>
        </div>
      </div>

      <SectionPanel
        className="bot-quiet-panel"
        title={
          <span className="bot-panel-title">
            <Clock3 size={13} /> 静默策略
          </span>
        }
        trailing={
          <StatusPill state={quietHours ? "neutral" : "safe"}>
            {quietHours ? "SCHEDULED" : "ALWAYS ON"}
          </StatusPill>
        }
      >
        {quietHours ? (
          <>
            <div className="bot-quiet-bar" aria-label="静默时段时间轴">
              <div
                className="bot-quiet-bar__quiet"
                style={{
                  left: `${(quietHours[0] / 24) * 100}%`,
                  width: `${quietPercent}%`,
                }}
              />
              <div className="bot-quiet-bar__now" style={{ left: `${(currentHour / 24) * 100}%` }} />
            </div>
            <div className="bot-quiet-bar__label">
              <span>00</span><span>06</span><span>12</span><span>18</span><span>24</span>
            </div>
            <div className="bot-quiet-summary">
              <div className="bot-quiet-stat">
                <span className="kv-row__label">静默区间</span>
                <strong className="num">{fmtHour(quietHours[0])} – {fmtHour(quietHours[1])}</strong>
              </div>
              <div className="bot-quiet-stat">
                <span className="kv-row__label">当前状态</span>
                <strong className={`num ${inQuietNow ? "text-muted" : "text-positive"}`}>
                  {inQuietNow ? "静默中" : "活跃推送"}
                </strong>
              </div>
              <p className="bot-hint">ERROR / CRITICAL 始终绕过静默策略；WARNING / INFO 在静默区间内压下。</p>
            </div>
          </>
        ) : (
          <EmptyState icon={<Clock3 size={16} />}>未配置静默时段，告警默认始终推送。</EmptyState>
        )}
      </SectionPanel>
    </div>
  );
}
