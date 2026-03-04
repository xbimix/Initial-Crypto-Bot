"use client";

import { useEffect, useState } from "react";

type StatusData = {
  enabled: boolean;
  cooldown: number;
  symbols: string[];
};

export default function StatusCard() {
  const [status, setStatus] = useState<StatusData | null>(null);

  useEffect(() => {
    fetch("/api/status").then(r => r.json()).then(setStatus);
  }, []);

  if (!status) return null;

  return (
    <div className="p-4 bg-slate-800 rounded">
      <p>Status: {status.enabled ? "RUNNING" : "STOPPED"}</p>
      <p>Cooldown: {status.cooldown}s</p>
      <p>Symbols: {status.symbols.join(", ")}</p>
    </div>
  );
}
