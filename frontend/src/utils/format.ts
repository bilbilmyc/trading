/**
 * Centralized number / percent formatters. Previously these were duplicated
 * across 6+ files (TradePage, MarketsPage, PortfolioPage, ...).
 */

const NUMBER_FORMATTER_CACHE = new Map<number, Intl.NumberFormat>();

function getNumberFormatter(digits: number): Intl.NumberFormat {
  let f = NUMBER_FORMATTER_CACHE.get(digits);
  if (!f) {
    f = new Intl.NumberFormat("en-US", {
      maximumFractionDigits: digits,
      minimumFractionDigits: 0,
    });
    NUMBER_FORMATTER_CACHE.set(digits, f);
  }
  return f;
}

export function formatNumber(value: number | undefined | null, digits = 4): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "--";
  return getNumberFormatter(digits).format(value);
}

export function formatPercent(value: number | undefined | null, digits = 4): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "--";
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatSignedPercent(value: number | undefined | null, digits = 2): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "--";
  const v = value * 100;
  const sign = v > 0 ? "+" : v < 0 ? "" : "";
  return `${sign}${v.toFixed(digits)}%`;
}

export function formatUsd(value: number | undefined | null, digits = 2): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "--";
  return `$${formatNumber(value, digits)}`;
}
