"use client";

/**
 * Symbol selector
 * - Displays human-friendly symbols
 * - Backend normalizes on save
 */

const ALL_SYMBOLS = [
  "BTC/USDT",
  "ETH/USDT",
  "BNB/USDT",
  "SOL/USDT",
  "XRP/USDT",
  "ADA/USDT",
  "DOGE/USDT",
  "DOT/USDT",
  "LTC/USDT",
  "LINK/USDT",
  "UNI/USDT",
  "ATOM/USDT",
  "XLM/USDT",
  "AVAX/USDT",
  "MATIC/USDT",
  "SUI/USDT",
  "SEI/USDT",
];

type ConfigWithSymbols = {
  symbols: string[];
  [key: string]: unknown;
};

export default function SymbolSelector<T extends ConfigWithSymbols>({
  config,
  setConfig,
}: {
  config: T;
  setConfig: (cfg: T) => void;
}) {
  function toggle(symbol: string) {
    const next = config.symbols.includes(symbol)
      ? config.symbols.filter((s: string) => s !== symbol)
      : [...config.symbols, symbol];

    setConfig({ ...config, symbols: next } as T);
  }

  return (
    <div className="space-y-2">
      <h3>Symbols</h3>
      {ALL_SYMBOLS.map((s) => (
        <label key={s} className="block">
          <input
            type="checkbox"
            checked={config.symbols.includes(s)}
            onChange={() => toggle(s)}
          />{" "}
          {s}
        </label>
      ))}
    </div>
  );
}
