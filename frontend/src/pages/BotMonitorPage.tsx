/** Bot monitor page — settings + command catalog + quiet hours visualization.

Layout (3 columns on wide screens):
  ┌──────────────┬──────────────────────────┬──────────────┐
  │ Bot status   │ Command catalog table    │ Quiet hours  │
  │ + quick kill │ (with HTML preview)      │ bar + form   │
  └──────────────┴──────────────────────────┴──────────────┘

Data sources:
- /api/v1/engine/status — to derive bot state from monitor
- /api/v1/risk/kill-switch — to allow kill from this page
- (chat whitelist + token tail + state) — currently read from /api/v1/engine/status
  or stubbed if the backend hasn't yet exposed /api/v1/bot.

The page exists as a placeholder so the frontend has a place to land; wiring
more endpoints is a follow-up.
*/

import { useMemo, useState } from "react";
import { useEngine } from "../contexts/EngineContext";
import { useStatus } from "../contexts/StatusContext";
import { PageHeader } from "../components/PageHeader";
import { ProgressBar } from "../components/ProgressBar";
import { EmptyState } from "../components/atoms";

const COMMAND_CATALOG: Array<{
  cmd: string;
  category: string;
  brief: string;
}> = [
  { cmd: "/help",     category: "查询", brief: "列出所有可用命令" },
  { cmd: "/status",   category: "查询", brief: "引擎运行状态总览" },
  { cmd: "/pnl",      category: "查询", brief: "模拟盘资金 / 已实现 / 未实现" },
  { cmd: "/positions", category: "查询", brief: "当前持仓明细" },
  { cmd: "/signals",  category: "查询", brief: "最近 5 条策略信号" },
  { cmd: "/strategies", category: "查询", brief: "策略列表 + 运行状态" },
  { cmd: "/risk",     category: "查询", brief: "风控阈值实时状态" },
  { cmd: "/events",   category: "查询", brief: "最近 8 条审计事件" },
  { cmd: "/ticker SYMBOL", category: "查询", brief: "查行情（默认 BTCUSDT）" },
  { cmd: "/runner",   category: "查询", brief: "信号运行器周期数 / 最近错误" },
  { cmd: "/kill on [reason]",  category: "操作", brief: "启用 kill switch" },
  { cmd: "/kill off [reason]", category: "操作", brief: "关闭 kill switch" },
  { cmd: "/start_strategy NAME", category: "操作", brief: "启用策略" },
  { cmd: "/stop_strategy NAME",  category: "操作", brief: "停用策略" },
];

function fmtHour(h: number): string {
  return `${h.toString().padStart(2, "0")}:00`;
}

/** Local extension of EngineStatus carrying bot fields that
 *  haven't yet been wired into /api/v1/engine/status. */
interface BotAugment {
  bot_enabled?: boolean;
  bot_allowed_chat_ids?: number[];
  bot_token_tail?: string;
  bot_quiet_hours?: [number, number] | null;
  bot_min_alert_level?: string;
}

export function BotMonitorPage() {
  const { engine } = useEngine();
  const { killSwitch } = useStatus();
  const [flipPending, setFlipPending] = useState(false);

  // Bot state is currently a frontend placeholder — the backend
  // endpoint /api/v1/bot will replace these with real fields.
  const bot = engine as unknown as BotAugment | null;
  const botEnabled = bot?.bot_enabled ?? false;
  const botChats: number[] = bot?.bot_allowed_chat_ids ?? [];
  const tokenTail = bot?.bot_token_tail ?? "—";
  const quietHours = bot?.bot_quiet_hours ?? null;
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
    try {
      const enabled = !killSwitch?.enabled;
      await fetch("/api/v1/risk/kill-switch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled, reason: "bot_monitor_page" }),
      });
    } finally {
      setFlipPending(false);
    }
  }

  return (
    <>
      <PageHeader
        icon={<span aria-hidden>📡</span>}
        eyebrow="Bot 监控"
        title="Telegram Bot 监控盯盘"
        subtitle="从 bot 调用的命令表 / quiet hours / 与 kill switch 同屏"
      />

      <div className="bot-grid">
        {/* Column 1: Status + quick actions */}
        <section className="card">
          <h3 className="section-title-row">Bot 状态</h3>
          <div className="kv-row">
            <span className="kv-row__label">运行</span>
            <span className="kv-row__value num">
              {botEnabled ? "已启用" : "未启用"}
            </span>
          </div>
          <div className="kv-row">
            <span className="kv-row__label">Token 后 4 位</span>
            <span className="kv-row__value num">{tokenTail}</span>
          </div>
          <div className="kv-row">
            <span className="kv-row__label">允许 chat</span>
            <span className="kv-row__value num">
              {botChats.length > 0 ? botChats.length : "全部（开放）"}
            </span>
          </div>
          <div className="kv-row">
            <span className="kv-row__label">最小告警级别</span>
            <span className="kv-row__value num">
              {bot?.bot_min_alert_level ?? "warning"}
            </span>
          </div>

          <h4 className="section-title-row section-title-row--h4">快捷动作</h4>
          <button
            type="button"
            className={`btn ${killSwitch?.enabled ? "btn--safe" : "btn--danger"} bot-toggle`}
            onClick={toggleKill}
            disabled={flipPending}
          >
            {killSwitch?.enabled
              ? "✅ 关闭 Kill Switch"
              : "🚨 启用 Kill Switch"}
          </button>
          <p className="bot-hint">
            此按钮通过 <code>X-Bot-Scope: monitor</code> 头调用 API，
            与 bot 端发送 <code>/kill on</code> 等价。
          </p>
        </section>

        {/* Column 2: Command catalog */}
        <section className="card">
          <h3 className="section-title-row">命令速查</h3>
          <table className="bot-cmd-table">
            <thead>
              <tr>
                <th>命令</th>
                <th>分类</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              {COMMAND_CATALOG.map((c) => (
                <tr key={c.cmd}>
                  <td><code>{c.cmd}</code></td>
                  <td className="bot-cmd-category">{c.category}</td>
                  <td>{c.brief}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="bot-hint">
            以上命令由 <code>app/bot/commands.py</code> 处理，
            通过 <code>/api/v1/engine/status</code>、<code>/api/v1/risk/kill-switch</code> 等端点与引擎通信。
          </p>
        </section>

        {/* Column 3: Quiet hours */}
        <section className="card">
          <h3 className="section-title-row">静默策略</h3>
          {quietHours ? (
            <>
              <div className="bot-quiet-bar">
                <div
                  className="bot-quiet-bar__quiet"
                  style={{
                    left: `${(quietHours[0] / 24) * 100}%`,
                    width: `${quietPercent}%`,
                  }}
                />
                <div
                  className="bot-quiet-bar__now"
                  style={{ left: `${(currentHour / 24) * 100}%` }}
                />
              </div>
              <div className="bot-quiet-bar__label">
                <span>00</span>
                <span>06</span>
                <span>12</span>
                <span>18</span>
                <span>24</span>
              </div>
              <div className="kv-row kv-row--spaced">
                <span className="kv-row__label">静默区间</span>
                <span className="kv-row__value num">
                  {fmtHour(quietHours[0])} – {fmtHour(quietHours[1])}
                </span>
              </div>
              <div className="kv-row">
                <span className="kv-row__label">当前</span>
                <span
                  className={`kv-row__value num kv-row__value--tone-${inQuietNow ? "muted" : "positive"}`}
                >
                  {inQuietNow ? "静默中" : "活跃"}
                </span>
              </div>
              <p className="bot-hint">
                ERROR / CRITICAL 始终绕过静默策略；
                WARNING / INFO 在静默区间内压下。
              </p>
            </>
          ) : (
            <EmptyState>
              未配置静默时段（默认始终推送）
            </EmptyState>
          )}
        </section>
      </div>
    </>
  );
}
