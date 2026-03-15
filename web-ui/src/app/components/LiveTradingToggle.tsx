"use client";

import type { ChangeEvent } from "react";
import { buildMutatingAuthHeaders } from "../lib/mutatingAuthClient";

export default function LiveTradingToggle() {
  async function toggle(event: ChangeEvent<HTMLInputElement>) {
    await fetch("/api/live", {
      method: "POST",
      headers: buildMutatingAuthHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ enabled: event.target.checked }),
    });
  }

  return (
    <label className="flex items-center gap-2">
      <input type="checkbox" onChange={toggle} />
      Live Trading
    </label>
  );
}
