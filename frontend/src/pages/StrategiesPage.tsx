import { useState } from "react";
import { Sigma } from "lucide-react";

import { useEngine } from "../contexts/EngineContext";
import { api } from "../api";
import type { LLMAnalysisResult } from "../api";
import { AIReport } from "../components/AIReport";
import { Metric } from "../components/atoms";
import { Card } from "../components/Card";
import { ListRow } from "../components/ListRow";
import { PageHeader } from "../components/PageHeader";

export function StrategiesPage() {
  const { strategies, signals, refresh } = useEngine();
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
    <div className="page page--strategies">
      <PageHeader
        icon={<Sigma size={18} />}
        eyebrow="策略管理"
        title="Strategies"
        subtitle="SMA 创建 · LLM 策略配置 · 信号流"
      />

      <div className="metric-grid">
        <Metric label="已加载" value={String(strategies.length)} tone="muted" />
        <Metric
          label="运行中"
          value={String(strategies.filter((s) => s.running).length)}
          tone="positive"
        />
        <Metric label="最近信号" value={String(signals.length)} tone="muted" />
      </div>

      <Card title="AI 分析" subtitle="一次性大模型市场分析（不自动下单）">
        <div className="form-grid">
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
            <input
              value={aiSymbol}
              onChange={(e) => setAiSymbol(e.target.value)}
            />
          </label>
          <label className="field">
            <span>周期</span>
            <select
              value={aiInterval}
              onChange={(e) => setAiInterval(e.target.value)}
            >
              <option value="15m">15m</option>
              <option value="1h">1h</option>
              <option value="4h">4h</option>
              <option value="1d">1d</option>
            </select>
          </label>
          <div className="field">
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
        <AIReport data={aiReport as any} loading={aiBusy} />
      </Card>

      <Card title="新建 SMA 策略" subtitle="simple moving average crossover">
        <div className="form-grid">
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
            >
              {busy === "create" ? "创建中" : "创建 SMA"}
            </button>
          </div>
        </div>
      </Card>

      <Card title="已加载策略">
        <div className="strategy-list">
          {strategies.length ? (
            strategies.map((s) => (
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
            ))
          ) : (
            <div className="empty-state">暂无策略</div>
          )}
        </div>
      </Card>

      <Card title="信号流" subtitle="最近 10 条">
        <div className="signal-list">
          {signals.length ? (
            signals.slice(0, 10).map((s) => (
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
            ))
          ) : (
            <div className="empty-state">暂无信号</div>
          )}
        </div>
      </Card>
    </div>
  );
}
