import { useCallback, useEffect, useState } from "react";
import { Link } from "wouter";

import { api } from "../api";
import type { AppConfig } from "../api";
import { EmptyState, Metric, SectionTitle } from "../components/atoms";

const KNOWN_SOURCES = [
  { value: "binance_usdm", label: "Binance USDⓈ-M 永续" },
  { value: "okx_swap", label: "OKX 永续合约" },
  { value: "bitget_usdt_futures", label: "Bitget USDT 永续" },
];

const CUSTOM_SOURCES_KEY = "quant_trader_custom_sources";

function loadCustomSources(): Array<{ name: string; base_url: string }> {
  try {
    const raw = localStorage.getItem(CUSTOM_SOURCES_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

export function DataPage() {
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [customSources, setCustomSources] = useState(loadCustomSources());
  const [newName, setNewName] = useState("");
  const [newUrl, setNewUrl] = useState("");

  const refresh = useCallback(async () => {
    try {
      const c = await api.config();
      setConfig(c);
    } catch {
      // backend offline
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const enabledFromSettings =
    config?.exchanges
      ? Object.entries(config.exchanges)
          .filter(([_, v]) => v.enabled)
          .map(([name]) => name)
      : [];

  const dataSources = Array.from(new Set([...enabledFromSettings, ...customSources.map((s) => s.name)]));

  function addCustom() {
    if (!newName || !newUrl) return;
    const next = [...customSources, { name: newName, base_url: newUrl }];
    setCustomSources(next);
    localStorage.setItem(CUSTOM_SOURCES_KEY, JSON.stringify(next));
    setNewName("");
    setNewUrl("");
  }

  function removeCustom(name: string) {
    const next = customSources.filter((s) => s.name !== name);
    setCustomSources(next);
    localStorage.setItem(CUSTOM_SOURCES_KEY, JSON.stringify(next));
  }

  return (
    <div className="page page--data">
      <header className="page__header">
        <div>
          <p className="eyebrow">数据分析</p>
          <h1>Data Sources</h1>
          <span className="page__subtitle">
            公开市场数据 — 无需 API Key 即可查询
          </span>
        </div>
      </header>

      <div className="metric-grid">
        <Metric label="已注册数据源" value={String(dataSources.length)} tone="muted" />
        <Metric label="系统默认" value={String(enabledFromSettings.length)} tone="muted" />
        <Metric label="自定义" value={String(customSources.length)} tone="muted" />
      </div>

      <section className="panel">
        <SectionTitle
          title="已注册数据源"
          subtitle="公开行情无需鉴权；私有操作需要单独配置 key"
        />
        {dataSources.length ? (
          <div className="data-sources-table">
            <div className="data-sources-table__row data-sources-table__row--head">
              <span>名称</span>
              <span>类型</span>
              <span>状态</span>
              <span>地址</span>
              <span>操作</span>
            </div>
            {dataSources.map((name) => {
              const known = KNOWN_SOURCES.find((s) => s.value === name);
              const custom = customSources.find((s) => s.name === name);
              const isCustom = Boolean(custom);
              const display = known?.label ?? custom?.name ?? name;
              return (
                <div
                  key={name}
                  className="data-sources-table__row lift-hover"
                >
                  <span>
                    <strong>{display}</strong>
                    <small style={{ color: "var(--text-muted)", display: "block", fontSize: 11 }}>
                      {name}
                    </small>
                  </span>
                  <span
                    className={`data-sources-table__status data-sources-table__status--${isCustom ? "custom" : "builtin"}`}
                  >
                    {isCustom ? "自定义" : "系统默认"}
                  </span>
                  <span
                    style={{
                      color: "var(--positive)",
                      fontSize: 12,
                    }}
                  >
                    ● 在线
                  </span>
                  <span
                    style={{
                      color: "var(--text-muted)",
                      fontFamily: "var(--font-mono)",
                      fontSize: 12,
                      wordBreak: "break-all",
                    }}
                  >
                    {custom?.base_url || "(系统默认路由)"}
                  </span>
                  <span style={{ display: "flex", gap: 6 }}>
                    <Link
                      href={`/markets?source=${name}`}
                      className="action action--ghost"
                      style={{ fontSize: 12, padding: "4px 10px" }}
                    >
                      浏览行情
                    </Link>
                    {isCustom && (
                      <button
                        className="action action--ghost"
                        style={{ fontSize: 12, padding: "4px 10px" }}
                        onClick={() => removeCustom(name)}
                      >
                        移除
                      </button>
                    )}
                  </span>
                </div>
              );
            })}
          </div>
        ) : (
          <EmptyState>
            暂未注册任何数据源 — 在 .env 中启用 BINANCE / OKX / BITGET 任一交易所，
            或在下方添加自定义数据源
          </EmptyState>
        )}
      </section>

      <section className="panel">
        <SectionTitle
          title="添加自定义数据源"
          subtitle="任意 OpenAPI / CCXT 兼容 HTTP 接口（保存在 localStorage）"
        />
        <div className="form-grid">
          <label className="field">
            <span>名称</span>
            <input
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="my-venue"
            />
          </label>
          <label className="field">
            <span>Base URL</span>
            <input
              value={newUrl}
              onChange={(e) => setNewUrl(e.target.value)}
              placeholder="https://api.example.com/v1"
            />
          </label>
          <div className="field">
            <button
              className="action action--primary"
              onClick={addCustom}
              disabled={!newName || !newUrl}
            >
              添加
            </button>
          </div>
        </div>
        <p className="page__note">
          自定义数据源会出现在上方列表中，可在「行情」页查询 ticker / klines / 合约。
          涉及下单 / 持仓 / 余额时仍需要原生交易所适配器。
        </p>
      </section>
    </div>
  );
}