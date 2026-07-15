import type { AutocompleteOption } from "../components/AutocompleteInput";

export const DEFAULT_SYMBOLS = [
  "BTCUSDT",
  "ETHUSDT",
  "SOLUSDT",
  "BNBUSDT",
  "XRPUSDT",
  "ADAUSDT",
  "DOGEUSDT",
  "AVAXUSDT",
  "LINKUSDT",
  "DOTUSDT",
] as const;

export function buildSymbolOptions(symbols: Iterable<string> = DEFAULT_SYMBOLS): AutocompleteOption[] {
  const seen = new Set<string>();
  const values = [...DEFAULT_SYMBOLS, ...symbols];

  return values.reduce<AutocompleteOption[]>((options, rawSymbol) => {
    const value = rawSymbol.trim().toUpperCase();
    if (!value || seen.has(value)) return options;
    seen.add(value);

    const quote = value.endsWith("USDT") ? "USDT" : "";
    const base = quote ? value.slice(0, -quote.length) : value;
    options.push({
      value,
      description: quote ? `${base} / ${quote}` : base,
      keywords: [base, quote],
    });
    return options;
  }, []);
}
