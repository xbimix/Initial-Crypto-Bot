"use client";

export default function SymbolSelector({ config, setConfig }: any) {
  const symbols = ["BTC-USD", "ETH-USD", "SOL-USD"];

  function toggle(sym: string) {
    const list = config.symbols.includes(sym)
      ? config.symbols.filter((s: string) => s !== sym)
      : [...config.symbols, sym];

    setConfig({ ...config, symbols: list });
  }

  return (
    <div className="space-y-2">
      <h3 className="font-bold">Symbols</h3>
      {symbols.map((s) => (
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
