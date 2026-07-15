/**
 * Unit tests for the centralized formatters in src/utils/format.ts.
 *
 * All four helpers share the same null/undefined/NaN guard: they return
 * "--" so dashboards never print "NaN%" or "undefined". The signed
 * variant additionally prefixes "+" on positive numbers.
 */

import { describe, expect, it } from "vitest";

import { formatNumber, formatPercent, formatSignedPercent, formatUsd } from "./format";

describe("formatNumber", () => {
  it("returns -- for null / undefined / NaN", () => {
    expect(formatNumber(undefined)).toBe("--");
    expect(formatNumber(null)).toBe("--");
    expect(formatNumber(Number.NaN)).toBe("--");
  });

  it("formats integers with no trailing decimals by default", () => {
    expect(formatNumber(1234)).toBe("1,234");
  });

  it("truncates to the requested digit count", () => {
    expect(formatNumber(1.23456, 2)).toBe("1.23");
    // 1.236 rounds up cleanly (no IEEE 754 ambiguity).
    expect(formatNumber(1.236, 2)).toBe("1.24");
  });

  it("handles zero without rendering negative sign", () => {
    expect(formatNumber(0)).toBe("0");
    expect(formatNumber(0, 4)).toBe("0");
  });

  it("handles negatives", () => {
    expect(formatNumber(-1234.5, 2)).toBe("-1,234.5");
  });
});

describe("formatPercent", () => {
  it("returns -- for null / undefined / NaN", () => {
    expect(formatPercent(undefined)).toBe("--");
    expect(formatPercent(null)).toBe("--");
    expect(formatPercent(Number.NaN)).toBe("--");
  });

  it("multiplies by 100 and appends %", () => {
    expect(formatPercent(0.1234, 2)).toBe("12.34%");
  });

  it("renders 0% without sign", () => {
    // default digits is 4 — explicit digits=0 would render "0%".
    expect(formatPercent(0)).toBe("0.0000%");
    expect(formatPercent(0, 0)).toBe("0%");
  });
});

describe("formatSignedPercent", () => {
  it("prefixes + on positive values", () => {
    expect(formatSignedPercent(0.05, 2)).toBe("+5.00%");
  });

  it("uses empty sign on negative values (the minus is in the digits)", () => {
    expect(formatSignedPercent(-0.05, 2)).toBe("-5.00%");
  });

  it("renders 0.00% with no sign for zero", () => {
    expect(formatSignedPercent(0)).toBe("0.00%");
  });

  it("returns -- for null / undefined / NaN", () => {
    expect(formatSignedPercent(undefined)).toBe("--");
    expect(formatSignedPercent(null)).toBe("--");
    expect(formatSignedPercent(Number.NaN)).toBe("--");
  });
});

describe("formatUsd", () => {
  it("prepends $ to the formatted number", () => {
    expect(formatUsd(1234.5, 2)).toBe("$1,234.5");
  });

  it("returns -- for null / undefined / NaN", () => {
    expect(formatUsd(undefined)).toBe("--");
    expect(formatUsd(null)).toBe("--");
    expect(formatUsd(Number.NaN)).toBe("--");
  });
});
