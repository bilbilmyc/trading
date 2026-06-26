import type { CSSProperties } from "react";

export interface AIReportData {
  decision?: string;
  confidence?: number;
  reason?: string;
  stop_loss?: number | null;
  take_profit?: number | null;
  risk_level?: string;
  risk_note?: string;
  error_kind?: string | null;
  model?: string;
  analysis_time?: string;
  symbol?: string;
  interval?: string;
  candle_count?: number;
  cache_hit?: boolean;
}

interface AIReportProps {
  data: AIReportData | null;
  loading?: boolean;
}

const TONE_COLOR: Record<string, string> = {
  buy: "var(--positive)",
  sell: "var(--negative)",
  hold: "var(--text-muted)",
};

const RISK_TONE: Record<string, "default" | "positive" | "negative" | "warning" | "muted"> = {
  low: "positive",
  medium: "muted",
  high: "warning",
};

/**
 * Render an LLM analyze result as a structured card.
 * Decision banner uses traffic-light color; risk + SL/TP in metric grid.
 */
export function AIReport({ data, loading }: AIReportProps) {
  if (loading) {
    return (
      <div className="ai-report ai-report--loading">
        <div className="ai-report__skeleton" />
        <div className="ai-report__skeleton ai-report__skeleton--short" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="ai-report ai-report--empty">
        <p>尚未运行 AI 分析</p>
      </div>
    );
  }

  // Error / not-configured state.
  if (data.error_kind === "api_key_missing") {
    return (
      <div className="ai-report ai-report--config">
        <h3>未配置 LLM API Key</h3>
        <p>
          当前没有配置 <code>LLM_API_KEY</code>。请在 <code>.env</code> 中设置后重启服务即可启用 AI 分析。
          公开行情数据查询与策略信号功能不受影响。
        </p>
      </div>
    );
  }
  if (data.error_kind) {
    return (
      <div className="ai-report ai-report--error">
        <h3>AI 分析失败 · {data.error_kind}</h3>
        <p>{data.reason || "请稍后重试，或检查网络 / 配额。"}</p>
      </div>
    );
  }

  const decision = (data.decision ?? "hold").toLowerCase();
  const decisionColor = TONE_COLOR[decision] ?? TONE_COLOR.hold;

  return (
    <div className="ai-report">
      <header
        className="ai-report__decision"
        style={{ "--decision-color": decisionColor } as CSSProperties}
      >
        <div>
          <span className="ai-report__label">建议动作</span>
          <strong>{labelForDecision(decision)}</strong>
        </div>
        <div className="ai-report__confidence">
          <span className="ai-report__label">置信度</span>
          <strong>{((data.confidence ?? 0) * 100).toFixed(1)}%</strong>
        </div>
      </header>

      {data.reason && (
        <div className="ai-report__section">
          <h4>分析推理</h4>
          <p>{data.reason}</p>
        </div>
      )}

      <div className="ai-report__metrics">
        <div className="metric">
          <span className="metric__label">风险等级</span>
          <strong className={`metric__value metric__value--${RISK_TONE[data.risk_level ?? "medium"]}`}>
            {(data.risk_level ?? "medium").toUpperCase()}
          </strong>
        </div>
        {data.stop_loss != null && (
          <div className="metric">
            <span className="metric__label">建议止损</span>
            <strong className="metric__value">{formatPrice(data.stop_loss)}</strong>
          </div>
        )}
        {data.take_profit != null && (
          <div className="metric">
            <span className="metric__label">建议止盈</span>
            <strong className="metric__value metric__value--positive">{formatPrice(data.take_profit)}</strong>
          </div>
        )}
        {data.risk_note && (
          <div className="metric ai-report__risk-note">
            <span className="metric__label">风险提示</span>
            <strong>{data.risk_note}</strong>
          </div>
        )}
      </div>

      <footer className="ai-report__footer">
        <span>
          {data.model && `模型 ${data.model}`}
          {data.cache_hit && " · cache hit"}
          {data.analysis_time && ` · ${new Date(data.analysis_time).toLocaleString()}`}
        </span>
      </footer>
    </div>
  );
}

function labelForDecision(d: string): string {
  if (d === "buy") return "买入 / 做多";
  if (d === "sell") return "卖出 / 做空";
  return "观望 / 持仓";
}

function formatPrice(p: number): string {
  if (p >= 1000) return `$${p.toFixed(0)}`;
  if (p >= 1) return `$${p.toFixed(2)}`;
  return `$${p.toFixed(4)}`;
}