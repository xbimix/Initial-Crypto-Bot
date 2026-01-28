"use client";

export default function LiveTradingToggle() {
  async function toggle(e: any) {
    await fetch("/api/live", {
      method: "POST",
      body: JSON.stringify({ enabled: e.target.checked }),
    });
  }

  return (
    <label className="flex items-center gap-2">
      <input type="checkbox" onChange={toggle} />
      Live Trading
    </label>
  );
}
