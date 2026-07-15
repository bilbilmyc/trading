/**
 * Bot monitor page — settings + command catalog + quiet hours visualization.
 *
 * Data sources:
 *   - engine.bot (BotStatus, populated by /api/v1/engine/status.bot)
 *   - killSwitch (from StatusContext)
 *   - /api/v1/risk/kill-switch POST for the quick-toggle.
 */

import { useEffect, useMemo, useState } from "react";
import { useEngine } from "../contexts/EngineContext";
import { useStatus } from "../contexts/StatusContext";
import { api } from "../api";
import { PageHeader } from "../components/PageHeader";
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

export function BotMonitorPage() {
  const { engine, refresh } = useEngine();
  const { killSwitch } = useStatus();
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
            <span
              className={`kv-row__value num kv-row__value--tone-${botEnabled ? "positive" : "muted"}`}
            >
              {botEnabled ? "已启用" : "未启用"}
            </span>
          </div>
          <div className="kv-row">
            <span className="kv-row__label">Token 后 4 位</span>
            <span className="kv-row__value num">{tokenTail || "—"}</span>
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
              {bot?.min_alert_level ?? "warning"}
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
          {flipError ? (
            <p className="bot-hint bot-hint--err">{flipError}</p>
          ) : (
            <p className="bot-hint">
              此按钮等价于 bot 端发送
              <code> /kill {killSwitch?.enabled ? "off" : "on"}</code>——
              二者都调用 <code>/api/v1/risk/kill-switch</code>。
            </p>
          )}
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
