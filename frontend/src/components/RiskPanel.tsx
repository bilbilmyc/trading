import { AlertTriangle, Gauge, Power } from "lucide-react";
import type {
  AppConfig,
  AuditEvent,
  EngineStatus,
  PaperSummary,
  StrategyInfo,
} from "../api";
import { EmptyState, Metric, SectionTitle, StatusPill } from "./atoms";

const EVENT_LABELS: Record<string, string> = {
  live_trading_blocked: "实盘守卫拦截",
  kill_switch_enabled: "Kill Switch 开启",
  kill_switch_disabled: "Kill Switch 解除",
  kill_switch_blocked: "Kill Switch 拦截",
  order_rejected_by_risk: "风控拒单",
  live_order_submitted: "策略实盘下单",
  live_order_failed: "策略下单失败",
  spot_order_submitted: "现货订单提交",
  contract_order_submitted: "合约订单提交",
  order_cancel_requested: "撤单请求",
  cancel_all_requested: "批量撤单请求",
  leverage_changed: "杠杆调整",
};

function formatNumber(value: number | undefined, digits = 2): string {
  if (value === undefined || Number.isNaN(value)) return "--";
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: 0,
  }).format(value);
}

function formatEventType(eventType: string): string {
  return EVENT_LABELS[eventType] ?? eventType.replaceAll("_", " ");
}

interface RiskPanelProps {
  engine: EngineStatus | null;
  config: AppConfig | null;
  killSwitchEnabled: boolean;
  killBusy: boolean;
  onToggleKillSwitch: () => void;
  events: AuditEvent[];
  strategies: StrategyInfo[];
  strategyBusy: string;
  onToggleStrategy: (strategy: StrategyInfo) => void;
  onToggleStrategyMode: (strategy: StrategyInfo) => void;
  paper: PaperSummary | null;
  supportedExchanges: string[];
  enabledExchanges: string[];
}

export function RiskPanel(props: RiskPanelProps) {
  const risk = props.engine?.risk;
  const positions = props.engine?.positions;

  return (
    <aside className="panel panel--risk">
      <SectionTitle title="账户守卫" subtitle="风控 · 审计 · 策略 · 模拟盘" trailing={<Gauge size={20} />} />

      <div className={`kill-switch ${props.killSwitchEnabled ? "kill-switch--active" : ""}`}>
        <div>
          <strong>全局 Kill Switch</strong>
          <span>
            {props.killSwitchEnabled ? "已熔断全部真实交易" : "真实交易风控闸门正常"}
          </span>
        </div>
        <button
          className={`action ${props.killSwitchEnabled ? "action--safe" : "action--danger"}`}
          onClick={props.onToggleKillSwitch}
          disabled={props.killBusy}
          type="button"
        >
          <Power size={14} />
          {props.killBusy ? "处理中..." : props.killSwitchEnabled ? "解除" : "熔断"}
        </button>
      </div>

      <div className="metric-grid metric-grid--compact">
        <Metric
          label="每分钟订单"
          value={`${risk?.orders_last_minute ?? 0}/${risk?.max_orders_per_minute ?? 0}`}
          tone="muted"
        />
        <Metric
          label="当日 PnL"
          value={`$${formatNumber(risk?.daily_pnl ?? 0)}`}
          tone={(risk?.daily_pnl ?? 0) >= 0 ? "positive" : "negative"}
        />
        <Metric
          label="当前回撤"
          value={`${formatNumber((risk?.current_drawdown ?? 0) * 100)}%`}
          tone={(risk?.current_drawdown ?? 0) > 0.1 ? "warning" : "muted"}
        />
        <Metric
          label="活跃仓位"
          value={String(positions?.active_positions ?? 0)}
          tone="muted"
        />
      </div>

      <div className="block">
        <SectionTitle title="审计事件" subtitle={`${props.events.length} 条`} />
        <div className="event-list">
          {props.events.length ? (
            props.events
              .slice()
              .reverse()
              .slice(0, 10)
              .map((event) => (
                <div className={`event-row event-row--${event.level}`} key={event.id}>
                  <div className="event-row__marker" />
                  <div>
                    <strong>{formatEventType(event.event_type)}</strong>
                    <span>
                      {event.exchange ?? "--"} · {event.symbol ?? "--"} ·{" "}
                      {new Date(event.timestamp).toLocaleTimeString()}
                    </span>
                    <p>{event.message}</p>
                  </div>
                </div>
              ))
          ) : (
            <EmptyState>暂无订单或风控审计事件</EmptyState>
          )}
        </div>
      </div>

      <div className="block">
        <SectionTitle title="已加载策略" subtitle={`${props.strategies.length} 个`} />
        <div className="strategy-list">
          {props.strategies.length ? (
            props.strategies.map((strategy) => (
              <div className="strategy-row" key={strategy.name}>
                <div>
                  <strong>{strategy.name}</strong>
                  <span>
                    {strategy.class_name} · {strategy.exchange ?? "--"} · {strategy.symbol ?? "--"} ·{" "}
                    {strategy.interval ?? "1m"} · {strategy.mode === "paper" ? "模拟盘" : "只信号"}
                  </span>
                </div>
                <div className="strategy-row__actions">
                  <button
                    className={`action action--ghost ${strategy.mode === "paper" ? "is-on" : ""}`}
                    onClick={() => props.onToggleStrategyMode(strategy)}
                    disabled={props.strategyBusy === strategy.name}
                  >
                    {strategy.mode === "paper" ? "模拟" : "信号"}
                  </button>
                  <button
                    className={`action ${strategy.running ? "action--safe" : "action--ghost"}`}
                    onClick={() => props.onToggleStrategy(strategy)}
                    disabled={props.strategyBusy === strategy.name}
                  >
                    {props.strategyBusy === strategy.name
                      ? "更新中..."
                      : strategy.running
                        ? "运行中"
                        : "已停止"}
                  </button>
                </div>
              </div>
            ))
          ) : (
            <EmptyState>暂无策略</EmptyState>
          )}
        </div>
      </div>

      <div className="block">
        <SectionTitle title="模拟盘" subtitle={props.paper ? `权益 $${formatNumber(props.paper.equity)}` : "--"} />
        <div className="metric-grid metric-grid--compact">
          <Metric label="总盈亏" value={`$${formatNumber(props.paper?.total_pnl)}`} tone={(props.paper?.total_pnl ?? 0) >= 0 ? "positive" : "negative"} />
          <Metric label="未实现" value={`$${formatNumber(props.paper?.unrealized_pnl)}`} tone="muted" />
          <Metric label="持仓" value={String(props.paper?.active_positions ?? 0)} tone="muted" />
        </div>
        <div className="position-list">
          {props.paper?.positions.length ? (
            props.paper.positions.slice(0, 4).map((position) => (
              <div className="position-row" key={`${position.exchange}-${position.symbol}`}>
                <div>
                  <strong>{position.symbol}</strong>
                  <span>{position.exchange}</span>
                </div>
                <div>
                  <strong>{formatNumber(position.quantity, 6)}</strong>
                  <span className={(position.unrealized_pnl ?? 0) >= 0 ? "text-positive" : "text-negative"}>
                    ${formatNumber(position.unrealized_pnl)}
                  </span>
                </div>
              </div>
            ))
          ) : (
            <EmptyState>暂无模拟持仓</EmptyState>
          )}
        </div>
      </div>

      <div className="block">
        <SectionTitle title="本地持仓记录" subtitle={props.engine?.timestamp ? new Date(props.engine.timestamp).toLocaleTimeString() : "--"} />
        <div className="position-list">
          {positions?.positions.length ? (
            positions.positions.slice(0, 5).map((position) => (
              <div className="position-row" key={`${position.exchange}-${position.symbol}`}>
                <div>
                  <strong>{position.symbol}</strong>
                  <span>{position.exchange}</span>
                </div>
                <div>
                  <strong>{formatNumber(position.quantity, 6)}</strong>
                  <span className={(position.unrealized_pnl ?? 0) >= 0 ? "text-positive" : "text-negative"}>
                    {formatNumber(position.pnl_pct, 2)}%
                  </span>
                </div>
              </div>
            ))
          ) : (
            <EmptyState icon={<AlertTriangle size={16} />}>暂无本地持仓</EmptyState>
          )}
        </div>
      </div>

      <div className="block">
        <SectionTitle title="后端支持" subtitle={`${props.enabledExchanges.length}/${props.supportedExchanges.length} 已启用`} />
        <div className="exchange-chips">
          {props.supportedExchanges.map((name) => (
            <StatusPill
              key={name}
              state={props.enabledExchanges.includes(name) ? "ok" : "muted" as any}
            >
              {name}
            </StatusPill>
          ))}
        </div>
      </div>

      <div className="block">
        <SectionTitle title="运行时配置" />
        <div className="metric-grid metric-grid--compact">
          <Metric label="默认交易所" value={props.config?.default_exchange ?? "--"} tone="muted" />
          <Metric label="默认合约" value={props.config?.default_symbol ?? "--"} tone="muted" />
          <Metric label="存储" value={props.config?.persistence.driver ?? "--"} tone="muted" />
          <Metric label="数据库" value={props.config?.persistence.path ?? "--"} tone="muted" />
        </div>
      </div>
    </aside>
  );
}