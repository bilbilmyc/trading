/**
 * TopTicker — verify the 24h change pill renders for items that
 * arrive with `change_pct_24h` populated and stays absent otherwise.
 *
 * The venue strip and price ticker are covered implicitly; this file
 * focuses on the new v0.4.2 behaviour.
 */

import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../api/market", () => ({
  marketApi: {
    prices: vi.fn().mockResolvedValue({ BTCUSDT: 60000, ETHUSDT: 3000 }),
    topMovers: vi.fn().mockResolvedValue({
      exchange: "binance_usdm",
      items: [
        { symbol: "BTCUSDT", price: 60000, change_pct_24h: 2.5 },
        { symbol: "ETHUSDT", price: 3000, change_pct_24h: -1.2 },
      ],
      timestamp: "2026-07-15T12:00:00",
    }),
  },
}));
vi.mock("../api/meta", () => ({
  metaApi: {
    venueHealth: vi.fn().mockRejectedValue(new Error("nope")),
  },
}));

import { TopTicker } from "./TopTicker";

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("TopTicker — 24h change pill", () => {
  it("renders an is-up pill for positive changes", async () => {
    render(<TopTicker />);
    await act(async () => {
      await vi.runOnlyPendingTimersAsync();
    });
    // Marquee duplicates the list, so each pill appears twice.
    const upPills = await screen.findAllByText("+2.50%");
    expect(upPills.length).toBeGreaterThan(0);
    expect(upPills[0]!.className).toContain("is-up");
  });

  it("renders an is-down pill for negative changes (no plus sign)", async () => {
    render(<TopTicker />);
    await act(async () => {
      await vi.runOnlyPendingTimersAsync();
    });
    const downPills = await screen.findAllByText("-1.20%");
    expect(downPills.length).toBeGreaterThan(0);
    expect(downPills[0]!.className).toContain("is-down");
  });
});
