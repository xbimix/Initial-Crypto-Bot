"use client";

import type { ChangeEvent } from "react";

export default function LiveTradingToggle() {
  async function toggle(event: ChangeEvent<HTMLInputElement>) {
    await fetch("/api/live", {
      method: "POST",
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
