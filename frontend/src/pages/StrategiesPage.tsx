import { useState } from "react";
import { useEngine } from "../contexts/EngineContext";
import { api } from "../api";
import { EmptyState, Metric, SectionTitle } from "../components/atoms";

export function StrategiesPage() {
  const { strategies, signals, refresh } = useEngine();
  const [busy, setBusy] = useState("");
  const [name, setName] = useState("");
  const [shortWindow, setShortWindow] = useState("5");
  const [longWindow, setLongWindow] = useState("20");

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

  async function toggle(s: typeof strategies[number]) {
    setBusy(s.name);
    try {
      if (s.running) await api.stopStrategy(s.name);
      else await api.startStrategy(s.name);
      await refresh();
    } finally {
      setBusy("");
    }
  }

  async function toggleMode(s: typeof strategies[number]) {
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
      <header className="page__header">
        <div>
          <p className="eyebrow">策略管理</p>
          <h1>Strategies</h1>
          <span className="page__subtitle">SMA 创建 · LLM 策略配置 · 信号流</span>
        </div>
      </header>

      <div className="metric-grid">
        <Metric label="已加载" value={String(strategies.length)} tone="muted" />
        <Metric label="运行中" value={String(strategies.filter((s) => s.running).length)} tone="positive" />
        <Metric label="最近信号" value={String(signals.length)} tone="muted" />
      </div>

      <section className="panel">
        <SectionTitle title="新建 SMA 策略" subtitle="simple moving average crossover" />
        <div className="form-grid">
          <label className="field">
            <span>策略名（可空）</span>
            <input value={name} onChange={(e) => setName(e.target.value)} />
          </label>
          <label className="field">
            <span>短窗口</span>
            <input value={shortWindow} onChange={(e) => setShortWindow(e.target.value)} inputMode="numeric" />
          </label>
          <label className="field">
            <span>长窗口</span>
            <input value={longWindow} onChange={(e) => setLongWindow(e.target.value)} inputMode="numeric" />
          </label>
          <div className="field">
            <button className="action action--primary" onClick={createSma} disabled={busy === "create"}>
              {busy === "create" ? "创建中" : "创建 SMA"}
            </button>
          </div>
        </div>
      </section>

      <section className="panel">
        <SectionTitle title="已加载策略" />
        <div className="strategy-list">
          {strategies.length ? (
            strategies.map((s) => (
              <div className="strategy-row" key={s.name}>
                <div>
                  <strong>{s.name}</strong>
                  <span>{s.class_name} · {s.exchange ?? "--"} · {s.symbol ?? "--"} · {s.mode === "paper" ? "模拟盘" : "只信号"}</span>
                </div>
                <div className="strategy-row__actions">
                  <button
                    className={`action action--ghost ${s.mode === "paper" ? "is-on" : ""}`}
                    onClick={() => toggleMode(s)}
                    disabled={busy === s.name}
                  >
                    {s.mode === "paper" ? "模拟" : "信号"}
                  </button>
                  <button
                    className={`action ${s.running ? "action--safe" : "action--ghost"}`}
                    onClick={() => toggle(s)}
                    disabled={busy === s.name}
                  >
                    {s.running ? "运行中" : "已停止"}
                  </button>
                </div>
              </div>
            ))
          ) : (
            <EmptyState>暂无策略</EmptyState>
          )}
        </div>
      </section>

      <section className="panel">
        <SectionTitle title="信号流" subtitle="最近 10 条" />
        <div className="signal-list">
          {signals.length ? (
            signals.slice(0, 10).map((s) => (
              <div className="signal-row" key={`${s.strategy}-${s.symbol}-${s.timestamp}`}>
                <div>
                  <strong>{s.strategy}</strong>
                  <span>{s.symbol}</span>
                </div>
                <div className={s.action === "buy" ? "text-positive" : "text-negative"}>
                  <strong>{s.action === "buy" ? "买入" : s.action === "sell" ? "卖出" : "观望"}</strong>
                  <span>{new Date(s.timestamp).toLocaleTimeString()}</span>
                </div>
              </div>
            ))
          ) : (
            <EmptyState>暂无信号</EmptyState>
          )}
        </div>
      </section>
    </div>
  );
}