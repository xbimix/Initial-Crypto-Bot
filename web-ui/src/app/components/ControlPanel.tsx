"use client";

export default function ControlPanel() {
  async function send(action: "start" | "stop") {
    await fetch("/api/control", {
      method: "POST",
      body: JSON.stringify({ action }),
    });
  }

  return (
    <div className="flex gap-4">
      <button onClick={() => send("start")} className="btn bg-green-600">
        Start Bot
      </button>
      <button onClick={() => send("stop")} className="btn bg-red-600">
        Stop Bot
      </button>
    </div>
  );
}
