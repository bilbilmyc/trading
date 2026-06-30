import { useCallback, useEffect, useState } from "react";
import { Link } from "wouter";
import { Database } from "lucide-react";

import { api } from "../api";
import type { AppConfig } from "../api";
import { EmptyState, Metric } from "../components/atoms";
import { Card } from "../components/Card";
import { DataTable, type Column } from "../components/DataTable";
import { PageHeader } from "../components/PageHeader";

interface DataSourceRow {
  name: string;
  isCustom: boolean;
  display: string;
  customUrl?: string;
}

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

  const dataSources: DataSourceRow[] = Array.from(
    new Set([...enabledFromSettings, ...customSources.map((s) => s.name)]),
  ).map((name) => {
    const known = KNOWN_SOURCES.find((s) => s.value === name);
    const custom = customSources.find((s) => s.name === name);
    return {
      name,
      isCustom: Boolean(custom),
      display: known?.label ?? custom?.name ?? name,
      customUrl: custom?.base_url,
    };
  });

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

  const columns: Column<DataSourceRow>[] = [
    {
      key: "name",
      header: "名称",
      width: "1.2fr",
      render: (row) => (
        <div>
          <strong>{row.display}</strong>
          <small className="data-table__cell--muted">{row.name}</small>
        </div>
      ),
    },
    {
      key: "type",
      header: "类型",
      width: "0.7fr",
      render: (row) => (
        <span
          className={`data-sources-table__status data-sources-table__status--${row.isCustom ? "custom" : "builtin"}`}
        >
          {row.isCustom ? "自定义" : "系统默认"}
        </span>
      ),
    },
    {
      key: "status",
      header: "状态",
      width: "0.6fr",
      render: () => <span className="text-positive">● 在线</span>,
    },
    {
      key: "url",
      header: "地址",
      width: "1.4fr",
      render: (row) => (
        <span className="data-table__cell--mono">{row.customUrl || "(系统默认路由)"}</span>
      ),
    },
    {
      key: "actions",
      header: "操作",
      width: "auto",
      align: "right",
      render: (row) => (
        <span className="data-table__actions">
          <Link href={`/markets?source=${row.name}`} className="action action--ghost action--xs">
            浏览行情
          </Link>
          {row.isCustom ? (
            <button
              type="button"
              className="action action--ghost action--xs"
              onClick={() => removeCustom(row.name)}
            >
              移除
            </button>
          ) : null}
        </span>
      ),
    },
  ];

  return (
    <div className="page page--data">
      <PageHeader
        icon={<Database size={18} />}
        eyebrow="数据分析"
        title="数据源"
        subtitle="公开市场数据 — 无需 API Key 即可查询"
      />

      <div className="metric-grid">
        <Metric label="已注册数据源" value={String(dataSources.length)} tone="muted" />
        <Metric label="系统默认" value={String(enabledFromSettings.length)} tone="muted" />
        <Metric label="自定义" value={String(customSources.length)} tone="muted" />
      </div>

      {/* 2/3 + 1/3 split: the registered-sources table and the "add custom
          source" form share a row so the whole page fits in one viewport. */}
      <div className="page__grid page__grid--split">
        <Card title="已注册数据源" subtitle="公开行情无需鉴权；私有操作需要单独配置 key">
          {dataSources.length ? (
            <DataTable
              columns={columns}
              rows={dataSources}
              rowKey={(row) => row.name}
            />
          ) : (
            <EmptyState>
              暂未注册任何数据源 — 在 .env 中启用 BINANCE / OKX / BITGET 任一交易所，
              或在右侧添加自定义数据源
            </EmptyState>
          )}
        </Card>

        <Card title="添加自定义数据源" subtitle="任意 OpenAPI / CCXT 兼容 HTTP 接口（保存在 localStorage）">
          <div className="form-grid form-grid--stacked">
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
                type="button"
                className="action action--primary"
                onClick={addCustom}
                disabled={!newName || !newUrl}
              >
                添加
              </button>
            </div>
          </div>
          <p className="page__note">
            自定义数据源会出现在左侧列表中，可在「行情」页查询 ticker / klines / 合约。
            涉及下单 / 持仓 / 余额时仍需要原生交易所适配器。
          </p>
        </Card>
      </div>
    </div>
  );
}
