"use client";

export default function KillSwitch() {
  async function kill() {
    await fetch("/api/kill", { method: "POST" });
    alert("BOT DISABLED");
  }

  return (
    <button
      onClick={kill}
      className="bg-red-800 text-white px-4 py-2 rounded"
    >
      EMERGENCY STOP
    </button>
  );
}
