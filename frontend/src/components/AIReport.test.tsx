import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AIReport } from "./AIReport";

describe("AIReport", () => {
  it("renders the structured market thesis and deterministic snapshot", () => {
    render(
      <AIReport
        data={{
          decision: "buy",
          confidence: 0.82,
          reason: "趋势、动量与量能形成共振。",
          risk_level: "medium",
          risk_note: "防范阻力位附近回落",
          trend: "bullish",
          volatility: "high",
          summary: "上行结构仍在延续",
          key_support: 95000,
          key_resistance: 102000,
          entry_zone: "98000-99000",
          stop_loss: 94000,
          take_profit: 110000,
          position_pct: 0.2,
          bullish_factors: ["SMA5 高于 SMA20", "量比放大"],
          bearish_factors: ["RSI 接近超买区"],
          invalidation_condition: "跌破 94000",
          risk_reward_ratio: 2.5,
          analyzed_symbol: "BTCUSDT",
          analyzed_interval: "1h",
          candle_count: 30,
          technical_indicators: {
            data_quality: "sufficient",
            trend_bias: "bullish",
            sma_5: 99000,
            sma_20: 97000,
            rsi_14: 67.2,
            momentum_5_pct: 2.1,
            momentum_20_pct: 6.4,
            atr_pct: 1.8,
            volume_ratio: 1.35,
          },
        }}
      />,
    );

    expect(screen.getByRole("article", { name: "AI 市场分析报告" })).toBeInTheDocument();
    expect(screen.getByText("买入 / 做多")).toBeInTheDocument();
    expect(screen.getByText("上行结构仍在延续")).toBeInTheDocument();
    expect(screen.getByText("SMA5 高于 SMA20")).toBeInTheDocument();
    expect(screen.getByText("跌破 94000")).toBeInTheDocument();
    expect(screen.getByText("1 : 2.50")).toBeInTheDocument();
    expect(screen.getByText("BTCUSDT · 1h · 30 根K线")).toBeInTheDocument();
  });

  it("keeps safety rejection as a dedicated fail-closed state", () => {
    render(
      <AIReport
        data={{
          decision: "hold",
          confidence: 0,
          reason: "止损位方向错误，已拒绝执行。",
          risk_level: "high",
          risk_note: "安全拒绝",
          error_kind: "safety_rejected",
        }}
      />,
    );

    expect(screen.getByText("AI 建议已被交易安全护栏拒绝")).toBeInTheDocument();
    expect(screen.getByText(/止损位方向错误/)).toBeInTheDocument();
  });
});
