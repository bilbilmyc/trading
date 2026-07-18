import type { CSSProperties } from "react";

import type { LLMAnalysisResult, LLMTechnicalIndicators } from "../api";
import { Markdown } from "../utils/markdown";

export type AIReportData = LLMAnalysisResult;

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

const TREND_LABEL: Record<string, string> = {
  bullish: "偏多",
  bearish: "偏空",
  neutral: "中性",
};

const VOLATILITY_LABEL: Record<string, string> = {
  low: "低波动",
  medium: "中等波动",
  high: "高波动",
};

export function AIReport({ data, loading }: AIReportProps) {
  if (loading) {
    return (
      <div className="ai-report ai-report--loading" aria-live="polite" aria-busy="true">
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
  if (data.error_kind === "safety_rejected") {
    return (
      <div className="ai-report ai-report--error">
        <h3>AI 建议已被交易安全护栏拒绝</h3>
        <p>{data.reason || "模型给出的方向、止损或止盈与当前价格不一致，因此系统已安全降级为观望。"}</p>
      </div>
    );
  }
  if (data.error_kind === "circuit_open") {
    return (
      <div className="ai-report ai-report--error">
        <h3>AI 服务暂时保护中</h3>
        <p>{data.reason || "模型服务连续失败，系统已暂时熔断以避免重复请求；请稍后重试。"}</p>
      </div>
    );
  }
  if (data.error_kind === "rate_limited") {
    return (
      <div className="ai-report ai-report--error">
        <h3>AI 调用过于频繁</h3>
        <p>{data.reason || "系统正在限制请求频率，请稍后重试。"}</p>
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
  const bullishFactors = data.bullish_factors ?? [];
  const bearishFactors = data.bearish_factors ?? [];
  const hasEvidence = bullishFactors.length > 0 || bearishFactors.length > 0;

  return (
    <article
      className="ai-report"
      style={{ "--decision-color": decisionColor } as CSSProperties}
      aria-label="AI 市场分析报告"
    >
      <header className="ai-report__decision">
        <div>
          <span className="ai-report__label">建议动作</span>
          <strong>{labelForDecision(decision)}</strong>
        </div>
        <div className="ai-report__confidence">
          <span className="ai-report__label">置信度</span>
          <strong>{((data.confidence ?? 0) * 100).toFixed(1)}%</strong>
        </div>
      </header>

      <div className="ai-report__regime" aria-label="市场状态">
        <span>趋势 <strong>{TREND_LABEL[data.trend ?? "neutral"] ?? data.trend}</strong></span>
        <span>波动 <strong>{VOLATILITY_LABEL[data.volatility ?? "medium"] ?? data.volatility}</strong></span>
        <span>风险 <strong className={`metric__value--${RISK_TONE[data.risk_level ?? "medium"] ?? "muted"}`}>{(data.risk_level ?? "medium").toUpperCase()}</strong></span>
      </div>

      {data.summary && (
        <section className="ai-report__section">
          <h4>核心判断</h4>
          <p>{data.summary}</p>
        </section>
      )}

      {data.reason && (
        <section className="ai-report__section">
          <h4>综合推理</h4>
          <Markdown text={data.reason} />
        </section>
      )}

      <dl className="ai-report__metrics">
        <ReportMetric label="关键支撑" value={formatOptionalPrice(data.key_support)} />
        <ReportMetric label="关键阻力" value={formatOptionalPrice(data.key_resistance)} />
        <ReportMetric label="入场区间" value={data.entry_zone || "--"} />
        <ReportMetric label="建议仓位" value={formatPosition(data.position_pct)} />
        <ReportMetric label="建议止损" value={formatOptionalPrice(data.stop_loss)} />
        <ReportMetric label="建议止盈" value={formatOptionalPrice(data.take_profit)} positive />
        <ReportMetric label="风险收益比" value={data.risk_reward_ratio != null ? `1 : ${data.risk_reward_ratio.toFixed(2)}` : "--"} />
      </dl>

      {hasEvidence && (
        <section className="ai-report__section">
          <h4>证据交叉验证</h4>
          <div className="ai-report__evidence">
            <EvidenceList title="看多证据" tone="positive" items={bullishFactors} />
            <EvidenceList title="看空证据" tone="negative" items={bearishFactors} />
          </div>
        </section>
      )}

      <TechnicalSnapshot indicators={data.technical_indicators} />

      {(data.invalidation_condition || data.risk_note) && (
        <section className="ai-report__guardrail">
          {data.invalidation_condition && (
            <div>
              <span className="ai-report__label">判断失效条件</span>
              <strong>{data.invalidation_condition}</strong>
            </div>
          )}
          {data.risk_note && (
            <div>
              <span className="ai-report__label">风险提示</span>
              <strong>{data.risk_note}</strong>
            </div>
          )}
        </section>
      )}

      <footer className="ai-report__footer">
        <span>
          {[
            data.analyzed_symbol,
            data.analyzed_interval,
            data.candle_count ? `${data.candle_count} 根K线` : "",
            data.model ? `模型 ${data.model}` : "",
            data.cache_hit ? "缓存命中" : "",
            data.analysis_time ? new Date(data.analysis_time).toLocaleString() : "",
          ].filter(Boolean).join(" · ")}
        </span>
      </footer>
    </article>
  );
}

function ReportMetric({ label, value, positive = false }: { label: string; value: string; positive?: boolean }) {
  return (
    <div className="metric">
      <dt className="metric__label">{label}</dt>
      <dd className={`metric__value${positive && value !== "--" ? " metric__value--positive" : ""}`}>{value}</dd>
    </div>
  );
}

function EvidenceList({ title, tone, items }: { title: string; tone: "positive" | "negative"; items: string[] }) {
  return (
    <div className={`ai-report__evidence-column ai-report__evidence-column--${tone}`}>
      <strong>{title}</strong>
      {items.length > 0 ? (
        <ul>{items.map((item) => <li key={item}>{item}</li>)}</ul>
      ) : (
        <p>暂无明确证据</p>
      )}
    </div>
  );
}

function TechnicalSnapshot({ indicators }: { indicators?: LLMTechnicalIndicators | null }) {
  if (!indicators || indicators.data_quality === "unavailable") return null;
  const items = [
    ["引擎趋势", TREND_LABEL[indicators.trend_bias ?? "neutral"]],
    ["SMA 5 / 20", joinNumbers(indicators.sma_5, indicators.sma_20)],
    ["RSI 14", formatNumber(indicators.rsi_14)],
    ["动量 5 / 20", joinNumbers(indicators.momentum_5_pct, indicators.momentum_20_pct, "%")],
    ["ATR 占比", indicators.atr_pct != null ? `${indicators.atr_pct.toFixed(2)}%` : "--"],
    ["近期量比", indicators.volume_ratio != null ? indicators.volume_ratio.toFixed(2) : "--"],
  ];
  return (
    <section className="ai-report__section">
      <h4>确定性技术快照</h4>
      <dl className="ai-report__technical">
        {items.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value || "--"}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}

function labelForDecision(decision: string): string {
  if (decision === "buy") return "买入 / 做多";
  if (decision === "sell") return "卖出 / 做空";
  return "观望 / 持仓";
}

function formatOptionalPrice(price?: number | null): string {
  return price == null ? "--" : formatPrice(price);
}

function formatPrice(price: number): string {
  if (price >= 1000) return `$${price.toFixed(0)}`;
  if (price >= 1) return `$${price.toFixed(2)}`;
  return `$${price.toFixed(4)}`;
}

function formatPosition(position?: number): string {
  return position == null ? "--" : `${(position * 100).toFixed(1)}%`;
}

function formatNumber(value?: number | null): string {
  return value == null ? "--" : value.toFixed(2);
}

function joinNumbers(first?: number | null, second?: number | null, suffix = ""): string {
  if (first == null || second == null) return "--";
  return `${first.toFixed(2)}${suffix} / ${second.toFixed(2)}${suffix}`;
}
