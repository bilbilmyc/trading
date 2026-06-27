import { useState } from "react";
import { useStatus } from "../contexts/StatusContext";
import { api } from "../api";
import { Metric, SectionTitle } from "../components/atoms";

export function SettingsPage() {
  const { config, refresh } = useStatus();
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  // Webhook config (local state — could be persisted to localStorage).
  const [webhookUrl, setWebhookUrl] = useState(localStorage.getItem("webhook_url") ?? "");
  const [webhookEnabled, setWebhookEnabled] = useState(
    localStorage.getItem("webhook_enabled") === "true"
  );
  const [testBusy, setTestBusy] = useState(false);

  async function toggleLiveTrading() {
    if (!config) return;
    try {
      const next = !config.live_trading_enabled;
      if (next && !window.confirm("开启实盘？所有实盘下单、风控将被激活。")) return;
      await api.toggleLiveTrading(next);
      setMessage(`实盘已${next ? "开启" : "关闭"}`);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "切换实盘失败");
    }
  }

  function saveWebhook() {
    localStorage.setItem("webhook_url", webhookUrl);
    localStorage.setItem("webhook_enabled", String(webhookEnabled));
    setMessage("Webhook 配置已保存");
  }

  async function testWebhook() {
    if (!webhookUrl) {
      setError("请先填写 Webhook URL");
      return
    }
    setTestBusy(true)
    setError("")
    try {
      // Send a test notification to the configured URL.
      const response = await fetch(webhookUrl, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: "Quant Trader Test",
          message: "This is a test notification",
          severity: "info",
          timestamp: new Date().toISOString(),
          extra: { source: "settings-page" },
        }),
      })
      if (response.ok) {
        setMessage(`测试成功 · HTTP ${response.status}`)
      } else {
        setError(`Webhook 返回 ${response.status}`)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Webhook 测试失败")
    } finally {
      setTestBusy(false)
    }
  }

  return (
    <div className="page page--settings">
      <header className="page__header">
        <div>
          <p className="eyebrow">系统配置</p>
          <h1>设置</h1>
          <span className="page__subtitle">实盘开关 · 交易所能力 · 运行时配置 · 通知 webhook</span>
        </div>
      </header>

      <div className="page__grid page__grid--two-thirds">
        <section className="panel">
          <SectionTitle title="实盘交易" subtitle="live_trading_enabled" />
          <div className="settings-row">
            <Metric
              label="实盘状态"
              value={config?.live_trading_enabled ? "已开启" : "已关闭"}
              tone={config?.live_trading_enabled ? "warning" : "positive"}
            />
            <button
              className={`action ${config?.live_trading_enabled ? "action--safe" : "action--primary"}`}
              onClick={toggleLiveTrading}
            >
              {config?.live_trading_enabled ? "关闭实盘" : "开启实盘"}
            </button>
          </div>
        </section>

        <section className="panel">
          <SectionTitle title="通知 Webhook" subtitle="telegram / discord / slack / 自定义" />
          <p className="page__note">
            告警、下单、风险事件会 POST 到此 URL。Payload 为 JSON：
            <code>{"{title, message, severity, timestamp, extra}"}</code>。
          </p>
          <div className="form-grid">
            <label className="field">
              <span>Webhook URL</span>
              <input
                value={webhookUrl}
                onChange={(e) => setWebhookUrl(e.target.value)}
                placeholder="https://api.telegram.org/bot.../sendMessage 或 https://hooks.slack.com/..."
              />
            </label>
            <label className="field">
              <span>启用</span>
              <select
                value={webhookEnabled ? "true" : "false"}
                onChange={(e) => setWebhookEnabled(e.target.value === "true")}
              >
                <option value="false">关闭</option>
                <option value="true">开启</option>
              </select>
            </label>
          </div>
          <div className="action-row">
            <button
              className="action action--secondary"
              onClick={saveWebhook}
              disabled={!webhookUrl}
            >
              保存
            </button>
            <button
              className="action action--primary"
              onClick={testWebhook}
              disabled={!webhookUrl || testBusy}
            >
              {testBusy ? "测试中..." : "测试"}
            </button>
          </div>
          {error && <div className="notice notice--error">{error}</div>}
          {message && <div className="notice notice--info">{message}</div>}
        </section>

        <section className="panel">
          <SectionTitle title="交易所能力" subtitle="capabilities" />
          <div className="cap-grid">
            {config && Object.entries(config.exchange_capabilities).map(([name, caps]) => (
              <div key={name} className="cap-card">
                <strong>{name}</strong>
                <ul>
                  <li className={caps.supports_hedge_mode ? "ok" : "no"}>对冲模式</li>
                  <li className={caps.supports_post_only ? "ok" : "no"}>Post-only</li>
                  <li className={caps.supports_public_fee_lookup ? "ok" : "no"}>公开费率</li>
                  <li className={caps.supports_private_fee_lookup ? "ok" : "no"}>私有费率</li>
                </ul>
              </div>
            ))}
          </div>
        </section>

        <section className="panel">
          <SectionTitle title="运行时" subtitle="runtime" />
          <div className="metric-grid">
            <Metric label="默认交易所" value={config?.default_exchange ?? "--"} tone="muted" />
            <Metric label="默认合约" value={config?.default_symbol ?? "--"} tone="muted" />
            <Metric label="存储驱动" value={config?.persistence.driver ?? "--"} tone="muted" />
            <Metric label="数据库" value={config?.persistence.path ?? "--"} tone="muted" />
          </div>
        </section>

        <section className="panel">
          <SectionTitle title="LLM 配置" subtitle="openai-compatible" />
          <p className="page__note">
            LLM API 配置从环境变量读取（<code>LLM_API_KEY</code>, <code>LLM_BASE_URL</code>, <code>LLM_MODEL</code>）。
            启用实盘 LLM 策略前请确保 <code>LLM_API_KEY</code> 已设置并重启服务。
          </p>
        </section>
      </div>
    </div>
  );
}