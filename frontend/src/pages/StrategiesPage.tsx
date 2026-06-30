import { useState } from "react";
import { Sigma } from "lucide-react";

import { useEngine } from "../contexts/EngineContext";
import { api } from "../api";
import type { LLMAnalysisResult } from "../api";
import { AIReport } from "../components/AIReport";
import { Metric, MetricTile } from "../components/atoms";
import { Card } from "../components/Card";
import { KPIHero } from "../components/KPIHero";
import { ListRow } from "../components/ListRow";
import { PageHeader } from "../components/PageHeader";

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

  return (
    <div className="page page--strategies stack">
      <PageHeader
        icon={<Sigma size={18} />}
        eyebrow="策略管理"
        title="Strategies"
        subtitle="SMA 创建 · LLM 策略配置 · 信号流"
      />

      {/* KPI strip — operational summary. */}
      <div className="kpi-strip kpi-strip--four">
        <KPIHero
          label="已加载策略"
          value={String(strategies.length)}
          icon={<Sigma size={12} />}
          iconGradient="indigo"
          sparkline={[3, 4, 5, 5, 5, 6, 5, 5, 5, 5]}
          hint={`${strategies.filter((s) => s.running).length} 运行中`}
        />
        <KPIHero
          label="最近信号"
          value={String(signals.length)}
          icon={<Sigma size={12} />}
          iconGradient="cyan"
          delta={{ value: "今天 +12", tone: "positive" }}
          sparkline={[0, 1, 3, 5, 4, 6, 8, 7, 9, 12, 10, 14]}
        />
        <KPIHero
          label="AI 决策"
          value={
            aiReport?.decision === "long"
              ? "做多"
              : aiReport?.decision === "short"
                ? "做空"
                : aiReport
                  ? "观望"
                  : "--"
          }
          icon={<Sigma size={12} />}
          iconGradient={
            aiReport?.decision === "long"
              ? "green"
              : aiReport?.decision === "short"
                ? "red"
                : "yellow"
          }
          hint={aiReport ? `置信度 ${(aiReport.confidence * 100).toFixed(0)}%` : "运行分析获取"}
        />
        <KPIHero
          label="引擎状态"
          value={engine?.running ? "运行" : "停止"}
          icon={<Sigma size={12} />}
          iconGradient={engine?.running ? "green" : "red"}
          sparkline={engine?.running ? [1, 1, 1, 1] : [1, 0, 0, 0]}
          hint={`${strategies.filter((s) => s.mode === "live").length} 实盘 · ${strategies.filter((s) => s.mode === "paper").length} 模拟`}
        />
      </div>

      <div className="metric-grid metric-grid--six">
        <MetricTile
          label="已加载"
          value={String(strategies.length)}
          icon={<Sigma size={16} />}
          iconGradient="indigo"
        />
        <MetricTile
          label="运行中"
          value={String(strategies.filter((s) => s.running).length)}
          icon={<span style={{ fontSize: 12, fontWeight: 700 }}>RUN</span>}
          iconGradient={strategies.some((s) => s.running) ? "green" : "indigo"}
        />
        <MetricTile
          label="最近信号"
          value={String(signals.length)}
          icon={<span style={{ fontSize: 12, fontWeight: 700 }}>SIG</span>}
          iconGradient="cyan"
        />
        <MetricTile
          label="AI 决策"
          value={
            aiReport?.decision === "long"
              ? "做多"
              : aiReport?.decision === "short"
                ? "做空"
                : aiReport
                  ? "观望"
                  : "--"
          }
          icon={<span style={{ fontSize: 12, fontWeight: 700 }}>AI</span>}
          iconGradient={
            aiReport?.decision === "long"
              ? "green"
              : aiReport?.decision === "short"
                ? "red"
                : "indigo"
          }
        />
        <MetricTile
          label="策略模式"
          value={
            strategies.some((s) => s.mode === "live")
              ? "实盘"
              : strategies.some((s) => s.mode === "paper")
                ? "模拟"
                : "--"
          }
          icon={<span style={{ fontSize: 12, fontWeight: 700 }}>MODE</span>}
          iconGradient="orange"
        />
        <MetricTile
          label="引擎状态"
          value={engine?.running ? "运行" : "停止"}
          icon={<span style={{ fontSize: 12, fontWeight: 700 }}>ENG</span>}
          iconGradient={engine?.running ? "green" : "red"}
        />
      </div>

      {/* AI form + AI report (with inline expand) share the left column;
          SMA form is in the right column. */}
      <div className="page__grid page__grid--split">
        <div style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
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
                <input value={aiSymbol} onChange={(e) => setAiSymbol(e.target.value)} />
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
              <AIReport data={aiReport as any} loading={aiBusy} />
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
              <input
                value={shortWindow}
                onChange={(e) => setShortWindow(e.target.value)}
                inputMode="numeric"
              />
            </label>
            <label className="field">
              <span>长窗口</span>
              <input
                value={longWindow}
                onChange={(e) => setLongWindow(e.target.value)}
                inputMode="numeric"
              />
            </label>
            <div className="field">
              <button
                type="button"
                className="action action--primary"
                onClick={createSma}
                disabled={busy === "create"}
                style={{ width: "100%" }}
              >
                {busy === "create" ? "创建中" : "创建 SMA"}
              </button>
            </div>
          </div>
        </Card>
      </div>

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
                        <span className="list-row__trailing" style={{ gap: 6 }}>
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
