import { useEffect, useState } from "react";
import { BrainCircuit, ClipboardList, RefreshCw, ShieldAlert, Timer } from "lucide-react";

import { api, type ExecutionIntent, type LLMInsights, type ReconciliationIssue, type ReconciliationStatus } from "../api";
import { useEngine } from "../contexts/EngineContext";
import { Metric } from "../components/atoms";
import { Card } from "../components/Card";
import { EmptyState } from "../components/EmptyState";
import { ExpandModal } from "../components/ExpandModal";
import { KPIHero } from "../components/KPIHero";
import { ListRow, type ListRowLevel } from "../components/ListRow";
import { PageHeader } from "../components/PageHeader";
import { Sparkline } from "../components/Sparkline";
import { useExpandable } from "../hooks/useExpandable";

const EVENT_LABELS: Record<string, string> = {
  live_trading_blocked: "实盘守卫拦截",
  kill_switch_enabled: "Kill Switch 开启",
  kill_switch_disabled: "Kill Switch 解除",
  kill_switch_blocked: "Kill Switch 拦截",
  account_reconciliation_blocked: "账户对账熔断",
  account_reconciliation_blocked_order: "账户差异拒单",
  account_reconciliation_recovered: "账户对账恢复",
  order_rejected_by_risk: "风控拒单",
  live_order_submitted: "策略实盘下单",
  live_order_failed: "策略下单失败",
  paper_order_filled: "纸盘成交",
};

function formatEventType(t: string): string {
  return EVENT_LABELS[t] ?? t.replaceAll("_", " ");
}

const LEVELS = ["all", "critical", "error", "warning", "info"] as const;
type Level = (typeof LEVELS)[number];

function levelToRowLevel(level: string): ListRowLevel | undefined {
  if (level === "critical" || level === "error" || level === "warning" || level === "info") {
    return level;
  }
  return undefined;
}

const INSIGHT_WINDOWS = [
  { label: "1h", minutes: 60 },
  { label: "24h", minutes: 24 * 60 },
  { label: "7d", minutes: 7 * 24 * 60 },
] as const;

function formatTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(value);
}

function formatLatency(value: number): string {
  if (value >= 1_000) return `${(value / 1_000).toFixed(2)}s`;
  return `${Math.round(value)}ms`;
}

export function AuditPage() {
  const { events } = useEngine();
  const [filter, setFilter] = useState<Level>("all");
  const [insightMinutes, setInsightMinutes] = useState(24 * 60);
  const [insights, setInsights] = useState<LLMInsights | null>(null);
  const [insightError, setInsightError] = useState<string | null>(null);
  const [insightLoading, setInsightLoading] = useState(true);
  const [executions, setExecutions] = useState<ExecutionIntent[]>([]);
  const [executionError, setExecutionError] = useState<string | null>(null);
  const [executionLoading, setExecutionLoading] = useState(true);
  const [reconciliation, setReconciliation] = useState<ReconciliationStatus | null>(null);
  const [reconciliationIssues, setReconciliationIssues] = useState<ReconciliationIssue[]>([]);
  const [reconciliationError, setReconciliationError] = useState<string | null>(null);
  const [reconciliationLoading, setReconciliationLoading] = useState(true);
  const all = useExpandable();

  useEffect(() => {
    let active = true;
    setInsightLoading(true);
    setInsightError(null);
    api
      .llmInsights({ minutes: insightMinutes })
      .then((data) => {
        if (active) setInsights(data);
      })
      .catch((error: unknown) => {
        if (active) {
          setInsights(null);
          setInsightError(error instanceof Error ? error.message : "AI 指标加载失败");
        }
      })
      .finally(() => {
        if (active) setInsightLoading(false);
      });
    return () => {
      active = false;
    };
  }, [insightMinutes]);

  const loadExecutions = () => {
    setExecutionLoading(true);
    setExecutionError(null);
    api
      .pendingExecutions()
      .then((data) => setExecutions(data.intents))
      .catch((error: unknown) => {
        setExecutions([]);
        setExecutionError(error instanceof Error ? error.message : "订单执行状态加载失败");
      })
      .finally(() => setExecutionLoading(false));
  };

  const loadReconciliation = () => {
    setReconciliationLoading(true);
    setReconciliationError(null);
    Promise.all([api.reconciliationStatus(), api.reconciliationIssues()])
      .then(([status, issues]) => {
        setReconciliation(status);
        setReconciliationIssues(issues.issues);
      })
      .catch((error: unknown) => {
        setReconciliation(null);
        setReconciliationIssues([]);
        setReconciliationError(error instanceof Error ? error.message : "账户对账状态加载失败");
      })
      .finally(() => setReconciliationLoading(false));
  };

  const recoverExchange = (exchange: string) => {
    const note = window.prompt(`确认以 ${exchange} 当前交易所账户状态为准，并解除该交易所新增开仓限制。请填写确认说明：`);
    if (!note?.trim()) return;
    setReconciliationLoading(true);
    api
      .recoverReconciliation(exchange, note.trim())
      .then(() => loadReconciliation())
      .catch((error: unknown) => {
        setReconciliationError(error instanceof Error ? error.message : "恢复对账失败");
        setReconciliationLoading(false);
      });
  };

  useEffect(() => {
    loadExecutions();
    loadReconciliation();
  }, []);

  const VISIBLE_COUNT = 12;

  const filtered = filter === "all" ? events : events.filter((e) => e.level === filter);

  const byLevel = events.reduce<Record<string, number>>((acc, e) => {
    acc[e.level] = (acc[e.level] ?? 0) + 1;
    return acc;
  }, {});

  const reversed = filtered.slice().reverse();

  return (
    <div className="page page--audit stack">
      <PageHeader
        icon={<ClipboardList size={18} />}
        eyebrow="审计事件"
        title="Audit"
        subtitle="完整事件流 · 按级别过滤 · 倒序"
      />

      {/* KPI strip — event severity summary. */}
      <div className="kpi-strip kpi-strip--four">
        <KPIHero
          label="Critical"
          value={String(byLevel.critical ?? 0)}
          icon={<ClipboardList size={12} />}
          iconGradient="red"
          sparkline={[0, 0, 1, 0, 0, 2, 0, 0]}
        />
        <KPIHero
          label="Error"
          value={String(byLevel.error ?? 0)}
          icon={<ClipboardList size={12} />}
          iconGradient="orange"
          sparkline={[1, 0, 2, 1, 0, 1, 2, 1]}
        />
        <KPIHero
          label="Warning"
          value={String(byLevel.warning ?? 0)}
          icon={<ClipboardList size={12} />}
          iconGradient="yellow"
          sparkline={[0, 1, 1, 2, 1, 3, 2, 4]}
        />
        <KPIHero
          label="Info"
          value={String(byLevel.info ?? 0)}
          icon={<ClipboardList size={12} />}
          iconGradient="cyan"
          sparkline={[3, 4, 5, 4, 6, 7, 6, 8]}
          hint={`共 ${events.length}`}
        />
      </div>

      <div className="metric-grid metric-grid--four">
        <Metric label="critical" value={String(byLevel.critical ?? 0)} tone="negative" />
        <Metric label="error" value={String(byLevel.error ?? 0)} tone="warning" />
        <Metric label="warning" value={String(byLevel.warning ?? 0)} tone="warning" />
        <Metric label="info" value={String(byLevel.info ?? 0)} tone="muted" />
      </div>

      <Card
        title="订单执行对账"
        subtitle="持久化执行意图 · 提交结果不明时禁止盲目重试"
        trailing={
          <button type="button" className="filter-chip" onClick={loadExecutions} disabled={executionLoading}>
            <RefreshCw size={13} className={executionLoading ? "spin" : undefined} />
            刷新
          </button>
        }
      >
        {executionLoading ? (
          <EmptyState variant="iconic" title="正在读取执行意图" hint="加载本地持久化订单账本" />
        ) : executionError ? (
          <EmptyState variant="iconic" title="执行对账暂不可用" hint={executionError} />
        ) : executions.length === 0 ? (
          <EmptyState variant="iconic" title="没有待对账订单" hint="所有已记录订单均已进入终态" />
        ) : (
          <>
            <div className="metric-grid metric-grid--four">
              <Metric label="总待处理" value={String(executions.length)} tone="muted" />
              <Metric
                label="结果不明"
                value={String(executions.filter((item) => item.status === "unknown" || item.status === "submitting").length)}
                tone="warning"
              />
              <Metric
                label="交易所已受理"
                value={String(executions.filter((item) => item.status === "submitted" || item.status === "pending").length)}
                tone="positive"
              />
              <Metric
                label="部分成交"
                value={String(executions.filter((item) => item.status === "partially_filled").length)}
                tone="muted"
              />
            </div>
            <div className="event-list">
              {executions.slice(0, 8).map((item) => {
                const uncertain = item.status === "unknown" || item.status === "submitting";
                return (
                  <ListRow
                    key={item.client_order_id}
                    leading={<span className="event-row__marker" />}
                    level={uncertain ? "warning" : "info"}
                    title={`${item.status.toUpperCase()} · ${item.symbol}`}
                    subtitle={`${item.exchange} · ${item.side.toUpperCase()} ${item.quantity} · client: ${item.client_order_id}${item.exchange_order_id ? ` · order: ${item.exchange_order_id}` : ""}${item.last_error ? ` · ${item.last_error}` : ""}`}
                  />
                );
              })}
            </div>
          </>
        )}
      </Card>

      <Card
        title="账户与持仓对账"
        subtitle="仓位差异会按交易所阻止新增风险订单；撤单、减仓与平仓不受影响"
        trailing={
          <button type="button" className="filter-chip" onClick={loadReconciliation} disabled={reconciliationLoading}>
            <RefreshCw size={13} className={reconciliationLoading ? "spin" : undefined} />
            刷新
          </button>
        }
      >
        {reconciliationLoading ? (
          <EmptyState variant="iconic" title="正在核对交易所账户" hint="读取最新余额、持仓与未解决差异" />
        ) : reconciliationError ? (
          <EmptyState variant="iconic" title="账户对账暂不可用" hint={reconciliationError} />
        ) : (
          <>
            <div className="metric-grid metric-grid--four">
              <Metric label="新增订单限制" value={reconciliation?.guard.blocked ? "已拦截" : "正常"} tone={reconciliation?.guard.blocked ? "negative" : "positive"} />
              <Metric label="受限交易所" value={String(reconciliation?.guard.blocked_count ?? 0)} tone={reconciliation?.guard.blocked ? "warning" : "muted"} />
              <Metric label="严重差异" value={String(reconciliation?.summary.critical_count ?? 0)} tone={(reconciliation?.summary.critical_count ?? 0) > 0 ? "negative" : "muted"} />
              <Metric label="余额提醒" value={String(reconciliation?.summary.warning_count ?? 0)} tone={(reconciliation?.summary.warning_count ?? 0) > 0 ? "warning" : "muted"} />
            </div>
            {(reconciliation?.guard.blocked_exchanges?.length ?? 0) > 0 && (
              <div className="filter-row">
                {reconciliation!.guard.blocked_exchanges!.map((block) => (
                  <button key={block.exchange} type="button" className="filter-chip is-active" onClick={() => recoverExchange(block.exchange)}>
                    <ShieldAlert size={13} />
                    确认并恢复 {block.exchange}
                  </button>
                ))}
              </div>
            )}
            {reconciliationIssues.length === 0 ? (
              <EmptyState variant="compact" title="没有未解决的账户差异" hint="最近一次已持久化的交易所状态与本地状态一致" />
            ) : (
              <div className="event-list">
                {reconciliationIssues.slice(0, 8).map((issue) => (
                  <ListRow
                    key={`${issue.exchange}-${issue.issue_key}`}
                    leading={<span className="event-row__marker" />}
                    level={issue.severity === "critical" ? "critical" : "warning"}
                    title={`${issue.severity.toUpperCase()} · ${issue.kind}`}
                    subtitle={`${issue.exchange} · ${issue.resource ?? "账户"} · ${new Date(issue.detected_at).toLocaleString()}`}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </Card>

      <Card
        title="AI 模型健康"
        subtitle={`基于持久化 LLM 审计事件 · ${insights?.calls_total ?? 0} 次请求`}
        trailing={
          <div className="filter-row filter-row--flush">
            {INSIGHT_WINDOWS.map((window) => (
              <button
                key={window.minutes}
                type="button"
                className={`filter-chip ${insightMinutes === window.minutes ? "is-active" : ""}`}
                onClick={() => setInsightMinutes(window.minutes)}
              >
                {window.label}
              </button>
            ))}
          </div>
        }
      >
        {insightLoading ? (
          <EmptyState variant="iconic" title="正在加载 AI 运行指标" hint="读取本地审计事件" />
        ) : insightError ? (
          <EmptyState variant="iconic" title="AI 指标暂不可用" hint={insightError} />
        ) : !insights || insights.calls_total === 0 ? (
          <EmptyState
            variant="iconic"
            title="该时间窗口暂无 AI 分析请求"
            hint="发起一次 AI 分析后，这里会显示成功率、延迟和 token 使用量"
          />
        ) : (
          <>
            <div className="kpi-strip kpi-strip--four">
              <KPIHero
                label="Success rate"
                value={`${insights.success_rate.toFixed(1)}%`}
                icon={<BrainCircuit size={12} />}
                iconGradient={insights.failed_calls === 0 ? "green" : "yellow"}
                hint={`${insights.successful_calls}/${insights.calls_total} 成功`}
              />
              <KPIHero
                label="P95 latency"
                value={formatLatency(insights.p95_latency_ms)}
                icon={<Timer size={12} />}
                iconGradient="cyan"
                hint={`平均 ${formatLatency(insights.avg_latency_ms)}`}
              />
              <KPIHero
                label="Tokens"
                value={formatTokens(insights.total_tokens)}
                icon={<BrainCircuit size={12} />}
                iconGradient="indigo"
                hint={`输入 ${formatTokens(insights.prompt_tokens)} · 输出 ${formatTokens(insights.completion_tokens)}`}
              />
              <KPIHero
                label="Guardrail"
                value={String(insights.safety_rejections)}
                icon={<ShieldAlert size={12} />}
                iconGradient={insights.safety_rejections > 0 ? "orange" : "green"}
                hint={insights.safety_rejections > 0 ? "安全护栏已拦截异常建议" : "未发现异常建议"}
              />
            </div>

            <div className="metric-grid metric-grid--four">
              <Metric label="buy / sell / hold" value={`${insights.decisions.buy} / ${insights.decisions.sell} / ${insights.decisions.hold}`} hint="仅统计成功响应" />
              <Metric label="失败请求" value={String(insights.failed_calls)} tone={insights.failed_calls ? "warning" : "positive"} hint={Object.entries(insights.failures).map(([kind, count]) => `${kind} ${count}`).join(" · ") || "无"} />
              <Metric label="模型数" value={String(insights.models.length)} tone="muted" hint={insights.models.map((item) => `${item.provider}/${item.model}`).join(" · ")} />
              <Metric label="审计采样上限" value={String(insights.event_limit)} tone="muted" hint="仅用于历史运营分析，不是账单估算" />
            </div>
          </>
        )}
      </Card>

      <div className="filter-row">
        {LEVELS.map((l) => (
          <button
            key={l}
            type="button"
            className={`filter-chip ${filter === l ? "is-active" : ""}`}
            onClick={() => setFilter(l)}
          >
            {l}
          </button>
        ))}
      </div>

      <Card
        title="事件流"
        subtitle={`${filtered.length} 条 · 显示前 ${Math.min(VISIBLE_COUNT, filtered.length)}`}
      >
        {filtered.length === 0 ? (
          <EmptyState
            variant="iconic"
            title="暂无该级别事件"
            hint="切到 all 或别的级别查看"
          />
        ) : (
          <>
            <div className="scroll-cap scroll-cap--lg">
              <div className="event-list">
                {reversed.slice(0, VISIBLE_COUNT).map((event) => (
                  <ListRow
                    key={event.id}
                    leading={<span className="event-row__marker" />}
                    level={levelToRowLevel(event.level)}
                    title={formatEventType(event.event_type)}
                    subtitle={`${event.exchange ?? "--"} · ${event.symbol ?? "--"} · ${new Date(
                      event.timestamp,
                    ).toLocaleString()}${event.message ? ` · ${event.message}` : ""}`}
                  />
                ))}
              </div>
            </div>
            <div className="expandable-foot">
              <span className="expandable-foot__count">
                {filtered.length > VISIBLE_COUNT
                  ? `隐藏 ${filtered.length - VISIBLE_COUNT} 条`
                  : "已显示全部"}
              </span>
              {filtered.length > VISIBLE_COUNT ? (
                <button type="button" className="expandable-link" onClick={all.open}>
                  展开全部 ({filtered.length}) ↗
                </button>
              ) : null}
            </div>
          </>
        )}
      </Card>

      <ExpandModal
        isOpen={all.isOpen}
        onClose={all.close}
        title="审计事件 · 全部"
        subtitle={`${filtered.length} 条 · 倒序`}
        toolbar={
          <div className="filter-row filter-row--flush">
            {LEVELS.map((l) => (
              <button
                key={l}
                type="button"
                className={`filter-chip ${filter === l ? "is-active" : ""}`}
                onClick={() => setFilter(l)}
              >
                {l}
              </button>
            ))}
          </div>
        }
      >
        <div className="event-list">
          {reversed.map((event) => (
            <ListRow
              key={event.id}
              leading={<span className="event-row__marker" />}
              level={levelToRowLevel(event.level)}
              title={formatEventType(event.event_type)}
              subtitle={`${event.exchange ?? "--"} · ${event.symbol ?? "--"} · ${new Date(
                event.timestamp,
              ).toLocaleString()}${event.message ? ` · ${event.message}` : ""}`}
            />
          ))}
        </div>
      </ExpandModal>
    </div>
  );
}
