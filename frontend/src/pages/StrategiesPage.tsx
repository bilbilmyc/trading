import { useState } from "react";
import { Sigma } from "lucide-react";

import { useEngine } from "../contexts/EngineContext";
import { api } from "../api";
import type {
  BacktestResult, ExchangeName, LLMAnalysisResult, StrategyPromotionReview, WalkForwardResult,
} from "../api";
import { AIReport } from "../components/AIReport";
import { AutocompleteInput } from "../components/AutocompleteInput";
import { Card } from "../components/Card";
import { ListRow } from "../components/ListRow";
import { MarketSnapshot } from "../components/MarketSnapshot";
import { PageHeader } from "../components/PageHeader";
import { buildSymbolOptions } from "../utils/symbols";

const SYMBOL_OPTIONS = buildSymbolOptions();
const WINDOW_OPTIONS = ["3", "5", "7", "10", "20", "30", "50", "100", "200"].map((value) => ({
  value,
  description: "SMA 窗口预设",
}));

export function StrategiesPage() {
  const { strategies, signals, refresh, engine } = useEngine();
  const [busy, setBusy] = useState("");
  const [name, setName] = useState("");
  const [shortWindow, setShortWindow] = useState("5");
  const [longWindow, setLongWindow] = useState("20");

  const [aiSymbol, setAiSymbol] = useState("BTCUSDT");
  const [aiInterval, setAiInterval] = useState("1h");
  const [aiExchange, setAiExchange] = useState("binance_usdm");
  const [aiReport, setAiReport] = useState<LLMAnalysisResult | null>(null);
  const [aiBusy, setAiBusy] = useState(false);
  const [aiError, setAiError] = useState("");
  const [aiExpanded, setAiExpanded] = useState(false);

  const [backtestSymbol, setBacktestSymbol] = useState("BTCUSDT");
  const [backtestExchange, setBacktestExchange] = useState<ExchangeName>("binance_usdm");
  const [backtestInterval, setBacktestInterval] = useState("1h");
  const [backtestShortWindow, setBacktestShortWindow] = useState("5");
  const [backtestLongWindow, setBacktestLongWindow] = useState("20");
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null);
  const [backtestBusy, setBacktestBusy] = useState(false);
  const [backtestError, setBacktestError] = useState("");
  const [governanceStrategy, setGovernanceStrategy] = useState("");
  const [governanceBusy, setGovernanceBusy] = useState("");
  const [governanceError, setGovernanceError] = useState("");
  const [walkForwardResult, setWalkForwardResult] = useState<WalkForwardResult | null>(null);
  const [promotionReview, setPromotionReview] = useState<StrategyPromotionReview | null>(null);

  const visibleStrategies = strategies.slice(0, 6);
  const visibleSignals = signals.slice(0, 6);

  async function runAiAnalyze() {
    setAiBusy(true);
    setAiError("");
    try {
      const result = await api.aiAnalyze({
        exchange: aiExchange,
        symbol: aiSymbol,
        interval: aiInterval,
        limit: 30,
      });
      setAiReport(result);
    } catch (err) {
      setAiError(err instanceof Error ? err.message : "AI 分析失败");
    } finally {
      setAiBusy(false);
    }
  }

  async function runBacktest() {
    const short = Number(backtestShortWindow);
    const long = Number(backtestLongWindow);
    if (!Number.isInteger(short) || !Number.isInteger(long) || short <= 0 || short >= long) {
      setBacktestError("短窗口必须为正整数，且小于长窗口");
      return;
    }

    setBacktestBusy(true);
    setBacktestError("");
    try {
      const klines = await api.klines(backtestExchange, backtestSymbol, backtestInterval, 300);
      const result = await api.run({
        klines,
        short_window: short,
        long_window: long,
        fee_rate: 0.001,
        slippage_rate: 0.0005,
      });
      setBacktestResult(result);
    } catch (err) {
      setBacktestError(err instanceof Error ? err.message : "回测失败");
    } finally {
      setBacktestBusy(false);
    }
  }

  const governedStrategy = strategies.find((strategy) => strategy.name === governanceStrategy)
    ?? strategies[0]
    ?? null;

  async function runWalkForward() {
    if (!governedStrategy) {
      setGovernanceError("请先创建或加载一个策略");
      return;
    }
    setGovernanceBusy("walk-forward");
    setGovernanceError("");
    try {
      const short = Number(governedStrategy.parameters.short_window ?? backtestShortWindow);
      const long = Number(governedStrategy.parameters.long_window ?? backtestLongWindow);
      if (!Number.isInteger(short) || !Number.isInteger(long) || short <= 0 || short >= long) {
        throw new Error("当前策略不是可验证的 SMA 参数组合");
      }
      const klines = await api.klines(
        (governedStrategy.exchange as ExchangeName | undefined) ?? backtestExchange,
        governedStrategy.symbol ?? backtestSymbol,
        governedStrategy.interval ?? backtestInterval,
        300,
      );
      const response = await api.runWalkForward(governedStrategy.name, {
        klines,
        short_window: short,
        long_window: long,
        train_size: 180,
        test_size: 60,
        step_size: 60,
        candidate_parameters: [
          { short_window: Math.max(2, short - 2), long_window: Math.max(short + 1, long - 5) },
          { short_window: short, long_window: long },
          { short_window: short + 2, long_window: long + 5 },
        ],
        fee_rate: 0.001,
        slippage_rate: 0.0005,
      });
      setWalkForwardResult(response.result);
      await refresh();
    } catch (err) {
      setGovernanceError(err instanceof Error ? err.message : "滚动回测失败");
    } finally {
      setGovernanceBusy("");
    }
  }

  async function evaluatePromotion() {
    if (!governedStrategy) return;
    setGovernanceBusy("promotion");
    setGovernanceError("");
    try {
      const response = await api.evaluatePromotion(governedStrategy.name);
      setPromotionReview(response.review);
    } catch (err) {
      setGovernanceError(err instanceof Error ? err.message : "模拟盘评审失败");
    } finally {
      setGovernanceBusy("");
    }
  }

  async function decidePromotion() {
    if (!governedStrategy || !promotionReview || promotionReview.status !== "eligible") return;
    const note = window.prompt("确认已复核样本外回测与模拟盘成交。填写审批说明：", "已复核风险与模拟盘证据");
    if (!note) return;
    setGovernanceBusy("decision");
    setGovernanceError("");
    try {
      const response = await api.decidePromotion(governedStrategy.name, promotionReview.id, {
        approved: true,
        note,
      });
      setPromotionReview(response.review);
    } catch (err) {
      setGovernanceError(err instanceof Error ? err.message : "审批记录失败");
    } finally {
      setGovernanceBusy("");
    }
  }

  async function createSma() {
    setBusy("create");
    try {
      await api.createSmaStrategy({
        name: name || undefined,
        exchange: "binance_usdm",
        symbol: "BTCUSDT",
        interval: "1m",
        short_window: Number(shortWindow),
        long_window: Number(longWindow),
        enabled: true,
        mode: "paper",
      });
      setName("");
      await refresh();
    } finally {
      setBusy("");
    }
  }

  async function toggle(s: (typeof strategies)[number]) {
    setBusy(s.name);
    try {
      if (s.running) await api.stopStrategy(s.name);
      else await api.startStrategy(s.name);
      await refresh();
    } finally {
      setBusy("");
    }
  }

  async function toggleMode(s: (typeof strategies)[number]) {
    setBusy(s.name);
    try {
      await api.setStrategyMode(s.name, s.mode === "paper" ? "signal" : "paper");
      await refresh();
    } finally {
      setBusy("");
    }
  }

  const aiDecisionText =
    aiReport?.decision === "buy"
      ? "做多"
      : aiReport?.decision === "sell"
        ? "做空"
        : aiReport
          ? "观望"
          : "--";


  return (
    <div className="page page--strategies stack">
      <PageHeader
        icon={<Sigma size={18} />}
        eyebrow="策略管理"
        title="Strategies"
        subtitle="SMA 创建 · LLM 策略配置 · 信号流"
      />

      {/* v0.4 stats strip — hairline tiles, tabular figures. */}
      <div className="market-snap-strip">
        <MarketSnapshot
          label="已加载策略"
          value={String(strategies.length)}
          icon={<Sigma size={12} />}
          sparkline={[3, 4, 5, 5, 5, 6, 5, 5, 5, 5]}
          hint={`${strategies.filter((s) => s.running).length} 运行中`}
        />
        <MarketSnapshot
          label="最近信号"
          value={String(signals.length)}
          icon={<Sigma size={12} />}
          delta={{ value: "今天 +12", tone: "positive" }}
          sparkline={[0, 1, 3, 5, 4, 6, 8, 7, 9, 12, 10, 14]}
        />
        <MarketSnapshot
          label="AI 决策"
          value={aiDecisionText}
          icon={<Sigma size={12} />}
          hint={
            aiReport
              ? `置信度 ${(aiReport.confidence * 100).toFixed(0)}%`
              : "运行分析获取"
          }
        />
        <MarketSnapshot
          label="引擎状态"
          value={engine?.running ? "运行" : "停止"}
          icon={<Sigma size={12} />}
          sparkline={engine?.running ? [1, 1, 1, 1] : [1, 0, 0, 0]}
          hint={`${strategies.filter((s) => s.mode === "live").length} 实盘 · ${strategies.filter((s) => s.mode === "paper").length} 模拟`}
        />
      </div>

      <div className="page__grid page__grid--split">
        <div className="strategies-col">
          <Card title="AI 分析" subtitle="大模型一次性市场分析（不自动下单）">
            <div className="form-grid form-grid--inline">
              <label className="field">
                <span>交易所</span>
                <select
                  value={aiExchange}
                  onChange={(e) => setAiExchange(e.target.value)}
                >
                  <option value="binance_usdm">Binance USDⓈ-M</option>
                  <option value="okx_swap">OKX 永续</option>
                  <option value="bitget_usdt_futures">Bitget USDT 永续</option>
                </select>
              </label>
              <label className="field">
                <span>合约</span>
                <AutocompleteInput
                  value={aiSymbol}
                  onChange={(value) => setAiSymbol(value.toUpperCase())}
                  options={SYMBOL_OPTIONS}
                  placeholder="输入 BTC、ETH、SOL…"
                  aria-label="AI 分析合约"
                />
              </label>
              <label className="field">
                <span>周期</span>
                <select value={aiInterval} onChange={(e) => setAiInterval(e.target.value)}>
                  <option value="15m">15m</option>
                  <option value="1h">1h</option>
                  <option value="4h">4h</option>
                  <option value="1d">1d</option>
                </select>
              </label>
              <div className="field">
                <span>&nbsp;</span>
                <button
                  type="button"
                  className="action action--primary"
                  onClick={runAiAnalyze}
                  disabled={aiBusy || !aiSymbol}
                >
                  {aiBusy ? "分析中..." : "运行 AI 分析"}
                </button>
              </div>
            </div>
            {aiError ? <div className="notice notice--error">{aiError}</div> : null}
            <div className={`scroll-cap scroll-cap--md${aiExpanded ? " is-expanded" : ""}`}>
              <AIReport data={aiReport} loading={aiBusy} />
            </div>
            {aiReport ? (
              <div className="expandable-foot">
                <span className="expandable-foot__count">
                  {aiExpanded ? "已展开完整报告" : "报告较长，启用滚动"}
                </span>
                <button
                  type="button"
                  className="expandable-link"
                  onClick={() => setAiExpanded((v) => !v)}
                >
                  {aiExpanded ? "收起" : "展开全部 ↕"}
                </button>
              </div>
            ) : null}
          </Card>
        </div>

        <Card title="新建 SMA 策略" subtitle="简单移动平均交叉">
          <div className="form-grid form-grid--stacked">
            <label className="field">
              <span>策略名（可空）</span>
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label className="field">
              <span>短窗口</span>
              <AutocompleteInput
                value={shortWindow}
                onChange={setShortWindow}
                options={WINDOW_OPTIONS}
                inputMode="numeric"
                placeholder="例如 5"
                aria-label="短窗口"
              />
            </label>
            <label className="field">
              <span>长窗口</span>
              <AutocompleteInput
                value={longWindow}
                onChange={setLongWindow}
                options={WINDOW_OPTIONS}
                inputMode="numeric"
                placeholder="例如 20"
                aria-label="长窗口"
              />
            </label>
            <div className="field">
              <button
                type="button"
                className="action action--primary strategies-create-btn"
                onClick={createSma}
                disabled={busy === "create"}
              >
                {busy === "create" ? "创建中" : "创建 SMA"}
              </button>
            </div>
          </div>
        </Card>
      </div>

      <Card
        title="SMA 回测"
        subtitle="下一根 K 线开盘成交 · 含 0.10% 手续费与 0.05% 不利滑点"
        trailing={
          <button
            type="button"
            className="action action--primary action--xs"
            onClick={runBacktest}
            disabled={backtestBusy}
          >
            {backtestBusy ? "回测中..." : "运行回测"}
          </button>
        }
      >
        <div className="form-grid form-grid--inline">
          <label className="field">
            <span>合约</span>
            <AutocompleteInput
              value={backtestSymbol}
              onChange={(value) => setBacktestSymbol(value.toUpperCase())}
              options={SYMBOL_OPTIONS}
              aria-label="回测合约"
            />
          </label>
          <label className="field">
            <span>交易所</span>
            <select
              value={backtestExchange}
              onChange={(e) => setBacktestExchange(e.target.value as ExchangeName)}
            >
              <option value="binance_usdm">Binance USDⓈ-M</option>
              <option value="bitget_usdt_futures">Bitget USDT Futures</option>
              <option value="okx_swap">OKX Swap</option>
            </select>
          </label>
          <label className="field">
            <span>周期</span>
            <select value={backtestInterval} onChange={(e) => setBacktestInterval(e.target.value)}>
              <option value="15m">15m</option>
              <option value="1h">1h</option>
              <option value="4h">4h</option>
              <option value="1d">1d</option>
            </select>
          </label>
          <label className="field">
            <span>短 / 长窗口</span>
            <div className="inline-input-pair">
              <input
                value={backtestShortWindow}
                onChange={(e) => setBacktestShortWindow(e.target.value)}
                inputMode="numeric"
                aria-label="回测短窗口"
              />
              <input
                value={backtestLongWindow}
                onChange={(e) => setBacktestLongWindow(e.target.value)}
                inputMode="numeric"
                aria-label="回测长窗口"
              />
            </div>
          </label>
        </div>
        {backtestError ? <div className="notice notice--error">{backtestError}</div> : null}
        {backtestResult ? (
          <div className="metric-grid backtest-metrics">
            <div className={`metric ${backtestResult.total_pnl >= 0 ? "metric--positive" : "metric--negative"}`}>
              <span className="metric__label">净收益</span>
              <strong className="metric__value">${backtestResult.total_pnl.toFixed(2)}</strong>
              <span className="metric__hint">{backtestResult.total_return_pct.toFixed(2)}%</span>
            </div>
            <div className="metric">
              <span className="metric__label">最终权益</span>
              <strong className="metric__value">${backtestResult.final_equity.toFixed(2)}</strong>
              <span className="metric__hint">{backtestResult.trades} 笔已完成交易</span>
            </div>
            <div className="metric metric--warning">
              <span className="metric__label">最大回撤</span>
              <strong className="metric__value">{(backtestResult.max_drawdown * 100).toFixed(2)}%</strong>
              <span className="metric__hint">手续费 ${backtestResult.total_fees.toFixed(2)}</span>
            </div>
            <div className="metric">
              <span className="metric__label">胜率 / 盈亏比</span>
              <strong className="metric__value">{(backtestResult.win_rate * 100).toFixed(1)}%</strong>
              <span className="metric__hint">
                {backtestResult.profit_factor === null
                  ? "盈亏比 —"
                  : `盈亏比 ${backtestResult.profit_factor.toFixed(2)}`}
              </span>
            </div>
          </div>
        ) : null}
      </Card>

      <Card
        title="策略治理"
        subtitle="版本留痕 · 严格样本外 Walk-Forward · 模拟盘人工晋级（不会自动切换实盘）"
      >
        <div className="form-grid form-grid--inline">
          <label className="field">
            <span>目标策略</span>
            <select
              value={governanceStrategy || governedStrategy?.name || ""}
              onChange={(event) => setGovernanceStrategy(event.target.value)}
              disabled={strategies.length === 0}
            >
              {strategies.map((strategy) => (
                <option key={strategy.name} value={strategy.name}>
                  {strategy.name} · v{strategy.version ?? "—"} · {strategy.mode === "paper" ? "模拟" : strategy.mode}
                </option>
              ))}
            </select>
          </label>
          <div className="field">
            <span>当前版本</span>
            <strong>v{governedStrategy?.version ?? "—"}</strong>
          </div>
          <div className="field">
            <span>&nbsp;</span>
            <button
              type="button"
              className="action action--primary"
              onClick={runWalkForward}
              disabled={!governedStrategy || Boolean(governanceBusy)}
            >
              {governanceBusy === "walk-forward" ? "验证中..." : "运行 Walk-Forward"}
            </button>
          </div>
          <div className="field">
            <span>&nbsp;</span>
            <button
              type="button"
              className="action action--ghost"
              onClick={evaluatePromotion}
              disabled={!governedStrategy || Boolean(governanceBusy)}
            >
              {governanceBusy === "promotion" ? "评审中..." : "评审模拟盘"}
            </button>
          </div>
        </div>
        {governanceError ? <div className="notice notice--error">{governanceError}</div> : null}
        {walkForwardResult ? (
          <div className="metric-grid">
            <div className="metric">
              <span className="metric__label">样本外收益</span>
              <strong className={walkForwardResult.total_return_pct >= 0 ? "text-positive" : "text-negative"}>
                {walkForwardResult.total_return_pct >= 0 ? "+" : ""}{walkForwardResult.total_return_pct.toFixed(2)}%
              </strong>
              <span className="metric__hint">{walkForwardResult.folds.length} 个独立窗口</span>
            </div>
            <div className="metric">
              <span className="metric__label">稳定性</span>
              <strong>{(walkForwardResult.profitable_fold_ratio * 100).toFixed(0)}%</strong>
              <span className="metric__hint">正收益窗口 · 波动 {walkForwardResult.return_stddev_pct.toFixed(2)}%</span>
            </div>
            <div className="metric metric--warning">
              <span className="metric__label">样本外最大回撤</span>
              <strong>{(walkForwardResult.max_drawdown * 100).toFixed(2)}%</strong>
              <span className="metric__hint">{walkForwardResult.trades} 笔已平仓交易</span>
            </div>
          </div>
        ) : null}
        {promotionReview ? (
          <div className={`notice ${promotionReview.status === "eligible" || promotionReview.status === "approved" ? "notice--success" : "notice--warning"}`}>
            <strong>模拟盘评审：{promotionReview.status}</strong>
            <span> · 版本 v{promotionReview.strategy_version} · 仅生成审计决策，不变更实盘模式。</span>
            {promotionReview.status === "eligible" ? (
              <button
                type="button"
                className="action action--xs action--ghost"
                onClick={decidePromotion}
                disabled={Boolean(governanceBusy)}
              >
                {governanceBusy === "decision" ? "记录中..." : "人工批准"}
              </button>
            ) : null}
          </div>
        ) : null}
      </Card>

      <div className="page__grid page__grid--two-thirds">
        <Card
          title="已加载策略"
          subtitle={`共 ${strategies.length} · 显示前 ${Math.min(6, strategies.length)}`}
        >
          {strategies.length === 0 ? (
            <div className="empty-state">
              <strong>暂无策略</strong>
              <span>下方表单可创建 SMA 策略</span>
            </div>
          ) : (
            <>
              <div className="scroll-cap scroll-cap--md">
                <div className="strategy-list">
                  {visibleStrategies.map((s) => (
                    <ListRow
                      key={s.name}
                      title={s.name}
                      subtitle={`${s.class_name} · ${s.exchange ?? "--"} · ${s.symbol ?? "--"} · ${
                        s.mode === "paper" ? "模拟盘" : "只信号"
                      }`}
                      trailing={
                        <span className="list-row__trailing strategies-row-actions">
                          <button
                            type="button"
                            className={`action action--ghost action--xs ${s.mode === "paper" ? "is-on" : ""}`}
                            onClick={() => toggleMode(s)}
                            disabled={busy === s.name}
                          >
                            {s.mode === "paper" ? "模拟" : "信号"}
                          </button>
                          <button
                            type="button"
                            className={`action action--xs ${s.running ? "action--safe" : "action--ghost"}`}
                            onClick={() => toggle(s)}
                            disabled={busy === s.name}
                          >
                            {s.running ? "运行中" : "已停止"}
                          </button>
                        </span>
                      }
                    />
                  ))}
                </div>
              </div>
              {strategies.length > 6 ? (
                <div className="expandable-foot">
                  <span className="expandable-foot__count">隐藏 {strategies.length - 6} 策略</span>
                </div>
              ) : null}
            </>
          )}
        </Card>

        <Card
          title="信号流"
          subtitle={`共 ${signals.length} 条 · 显示前 ${Math.min(6, signals.length)}`}
        >
          {signals.length === 0 ? (
            <div className="empty-state">
              <strong>暂无信号</strong>
              <span>启动 Runner 后会自动记录</span>
            </div>
          ) : (
            <>
              <div className="scroll-cap scroll-cap--sm">
                <div className="signal-list">
                  {visibleSignals.map((s) => (
                    <ListRow
                      key={`${s.strategy}-${s.symbol}-${s.timestamp}`}
                      title={s.strategy}
                      subtitle={s.symbol}
                      level={s.action === "buy" ? "success" : s.action === "sell" ? "error" : "info"}
                      trailing={
                        <div className={s.action === "buy" ? "text-positive" : "text-negative"}>
                          <strong>
                            {s.action === "buy" ? "买入" : s.action === "sell" ? "卖出" : "观望"}
                          </strong>
                          <div className="data-table__cell--muted">
                            {new Date(s.timestamp).toLocaleTimeString()}
                          </div>
                        </div>
                      }
                    />
                  ))}
                </div>
              </div>
              {signals.length > 6 ? (
                <div className="expandable-foot">
                  <span className="expandable-foot__count">隐藏 {signals.length - 6} 条</span>
                </div>
              ) : null}
            </>
          )}
        </Card>
      </div>
    </div>
  );
}
