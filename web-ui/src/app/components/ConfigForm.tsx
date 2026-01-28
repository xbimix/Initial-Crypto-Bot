"use client";

import { useEffect, useState } from "react";
import SymbolSelector from "./SymbolSelector";

export default function ConfigForm() {
  const [config, setConfig] = useState<any>(null);

  useEffect(() => {
    fetch("/api/config").then(r => r.json()).then(setConfig);
  }, []);

  if (!config) return <p>Loading config…</p>;

  async function save() {
    await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    });
    alert("Saved");
  }

  return (
    <div className="space-y-4 max-w-lg">
      <label>
        Buy Score
        <input
          className="input"
          type="number"
          value={config.strategy.buy_score_threshold}
          onChange={(e) =>
            setConfig({
              ...config,
              strategy: {
                ...config.strategy,
                buy_score_threshold: +e.target.value,
              },
            })
          }
        />
      </label>

      <label>
        Cooldown
        <input
          className="input"
          type="number"
          value={config.cooldown_seconds}
          onChange={(e) =>
            setConfig({ ...config, cooldown_seconds: +e.target.value })
          }
        />
      </label>

      <SymbolSelector config={config} setConfig={setConfig} />

      <button onClick={save} className="btn bg-blue-600">
        Save Config
      </button>
    </div>
  );
}
