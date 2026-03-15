"use client";

/**
 * Config editor UI
 * - Loads config safely
 * - Never crashes on invalid backend response
 * - Saves config back to Flask
 */

import { useEffect, useState } from "react";
import { buildMutatingAuthHeaders } from "../lib/mutatingAuthClient";
import SymbolSelector from "./SymbolSelector";

type DashboardConfig = {
  strategy: {
    buy_score_threshold: number;
  };
  cooldown_seconds: number;
  symbols: string[];
  [key: string]: unknown;
};

export default function ConfigForm() {
  const [config, setConfig] = useState<DashboardConfig | null>(null);

  useEffect(() => {
    const load = async () => {
      const res = await fetch("/api/config");
      const text = await res.text();

      if (!text) throw new Error("Empty response from backend");

      try {
        setConfig(JSON.parse(text) as DashboardConfig);
      } catch {
        console.error("Invalid JSON:", text);
      }
    };

    load().catch(console.error);
  }, []);

  if (!config) return <p>Loading config…</p>;

  async function save() {
    await fetch("/api/config", {
      method: "POST",
      headers: buildMutatingAuthHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(config),
    });
    alert("Saved");
  }

  return (
    <div className="space-y-4 max-w-lg">
      <label>
        Buy Score
        <input
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
          type="number"
          value={config.cooldown_seconds}
          onChange={(e) =>
            setConfig({ ...config, cooldown_seconds: +e.target.value })
          }
        />
      </label>

      <SymbolSelector config={config} setConfig={setConfig} />

      <button onClick={save}>Save Config</button>
    </div>
  );
}
