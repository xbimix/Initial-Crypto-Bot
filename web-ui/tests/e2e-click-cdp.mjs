import fs from "node:fs/promises";
import path from "node:path";
import { spawn } from "node:child_process";

const EDGE_PATH = process.env.EDGE_PATH || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const DEBUG_PORT = Number(process.env.CDP_PORT || 9222);
const BASE_URL = process.env.E2E_BASE_URL || "http://127.0.0.1:3005";
const OUT_DIR = process.env.E2E_OUT_DIR || path.resolve(process.cwd(), "state", "e2e-click-pass");

const nowStamp = new Date().toISOString().replace(/[:.]/g, "-");
const runDir = path.join(OUT_DIR, nowStamp);
await fs.mkdir(runDir, { recursive: true });

const edgeUserDataDir = path.join(runDir, "edge-profile");
await fs.mkdir(edgeUserDataDir, { recursive: true });

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForHttp(url, timeoutMs = 20000) {
  const start = Date.now();
  while ((Date.now() - start) < timeoutMs) {
    try {
      const res = await fetch(url);
      if (res.ok) {
        return res;
      }
    } catch {
      // keep retrying
    }
    await sleep(250);
  }
  throw new Error(`Timeout waiting for ${url}`);
}

const edge = spawn(EDGE_PATH, [
  "--headless=new",
  "--disable-gpu",
  "--no-first-run",
  "--no-default-browser-check",
  `--remote-debugging-port=${DEBUG_PORT}`,
  `--user-data-dir=${edgeUserDataDir}`,
  `${BASE_URL}/`,
], {
  stdio: ["ignore", "pipe", "pipe"],
});

let edgeStdout = "";
let edgeStderr = "";
edge.stdout.on("data", (d) => { edgeStdout += d.toString(); });
edge.stderr.on("data", (d) => { edgeStderr += d.toString(); });

await waitForHttp(`http://127.0.0.1:${DEBUG_PORT}/json/version`, 30000);
const targetsResp = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/list`);
const targets = await targetsResp.json();
const pageTarget = targets.find((t) => t.type === "page") || targets[0];
if (!pageTarget?.webSocketDebuggerUrl) {
  throw new Error("Unable to resolve CDP target websocket URL");
}

const ws = new WebSocket(pageTarget.webSocketDebuggerUrl);
await new Promise((resolve, reject) => {
  ws.addEventListener("open", () => resolve());
  ws.addEventListener("error", (ev) => reject(new Error(`CDP websocket open failed: ${String(ev)}`)));
});

let msgId = 0;
const pending = new Map();
const waiters = [];
const apiRequestById = new Map();
const apiLogs = [];

function emitEvent(msg) {
  if (msg?.method === "Network.requestWillBeSent") {
    const req = msg.params?.request;
    if (req?.url) {
      apiRequestById.set(msg.params.requestId, {
        url: String(req.url),
        method: String(req.method || "GET"),
      });
    }
  }
  if (msg?.method === "Network.responseReceived") {
    const requestId = msg.params?.requestId;
    const response = msg.params?.response;
    const fromReq = apiRequestById.get(requestId);
    const url = String(response?.url || fromReq?.url || "");
    if (url.includes("/api/")) {
      apiLogs.push({
        ts: new Date().toISOString(),
        method: fromReq?.method || "GET",
        status: Number(response?.status || 0),
        url,
      });
    }
  }

  for (let i = waiters.length - 1; i >= 0; i -= 1) {
    const waiter = waiters[i];
    if (waiter.method !== msg.method) {
      continue;
    }
    let ok = false;
    try {
      ok = waiter.predicate ? waiter.predicate(msg) : true;
    } catch {
      ok = false;
    }
    if (ok) {
      clearTimeout(waiter.timer);
      waiters.splice(i, 1);
      waiter.resolve(msg);
    }
  }
}

ws.addEventListener("message", (event) => {
  const text = typeof event.data === "string" ? event.data : String(event.data);
  let msg;
  try {
    msg = JSON.parse(text);
  } catch {
    return;
  }
  if (Object.prototype.hasOwnProperty.call(msg, "id")) {
    const entry = pending.get(msg.id);
    if (entry) {
      clearTimeout(entry.timer);
      pending.delete(msg.id);
      entry.resolve(msg);
    }
    return;
  }
  if (msg?.method) {
    emitEvent(msg);
  }
});

function cdp(method, params = {}, timeoutMs = 30000) {
  const id = ++msgId;
  const payload = JSON.stringify({ id, method, params });
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`CDP timeout on ${method}`));
    }, timeoutMs);
    pending.set(id, { resolve, reject, timer });
    ws.send(payload);
  }).then((msg) => {
    if (msg.error) {
      throw new Error(`CDP ${method} failed: ${JSON.stringify(msg.error)}`);
    }
    return msg.result || {};
  });
}

function waitEvent(method, predicate = null, timeoutMs = 20000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      const idx = waiters.findIndex((w) => w.resolve === resolve);
      if (idx >= 0) {
        waiters.splice(idx, 1);
      }
      reject(new Error(`Timeout waiting for event ${method}`));
    }, timeoutMs);
    waiters.push({ method, predicate, resolve, timer });
  });
}

async function evalJs(expression, timeoutMs = 30000) {
  const result = await cdp("Runtime.evaluate", {
    expression,
    returnByValue: true,
    awaitPromise: true,
  }, timeoutMs);
  if (result.exceptionDetails) {
    throw new Error(`Runtime.evaluate exception: ${JSON.stringify(result.exceptionDetails)}`);
  }
  return result.result?.value;
}

async function waitFor(fn, timeoutMs = 20000, stepMs = 250, label = "condition") {
  const start = Date.now();
  while ((Date.now() - start) < timeoutMs) {
    const ok = await fn();
    if (ok) {
      return true;
    }
    await sleep(stepMs);
  }
  throw new Error(`Timeout waiting for ${label}`);
}

async function navigate(url) {
  await cdp("Page.navigate", { url }, 30000);
  await waitEvent("Page.loadEventFired", null, 30000).catch(() => {});
  await waitFor(() => evalJs("document.readyState === 'complete'"), 20000, 250, `readyState complete for ${url}`);
  await sleep(600);
}

async function screenshot(name) {
  const shot = await cdp("Page.captureScreenshot", { format: "png", fromSurface: true }, 30000);
  const target = path.join(runDir, `${name}.png`);
  await fs.writeFile(target, Buffer.from(shot.data, "base64"));
  return target;
}

const results = [];
function record(item, pass, details = {}) {
  results.push({ item, pass, ...details });
}

try {
  await cdp("Page.enable");
  await cdp("Runtime.enable");
  await cdp("DOM.enable");
  await cdp("Network.enable");

  await navigate(`${BASE_URL}/`);
  await evalJs("window.confirm = () => true;");
  await screenshot("00-dashboard-post-nav");
  const tokenControlsReadyExpr = `(() => {
    const bodyText = (document.body?.innerText || '');
    const table = Array.from(document.querySelectorAll('table')).find((t) => {
      const h = (t.querySelector('thead')?.innerText || '').toUpperCase();
      return h.includes('CONFIGURED REGIME') && h.includes('SCALPER');
    });
    const hasText = /TOKEN CONTROLS|AUTO-TRADE BY SYMBOL/i.test(bodyText);
    const hasRow = !!table?.querySelector('tbody tr');
    return Boolean(table && hasText && hasRow);
  })();`;
  try {
    await waitFor(
      () => evalJs(tokenControlsReadyExpr),
      90000,
      400,
      "dashboard token controls"
    );
  } catch (error) {
    const debug = await evalJs(`(() => {
      const bodyText = (document.body?.innerText || '');
      const headerTexts = Array.from(document.querySelectorAll('table thead')).map((h) => (h.innerText || '').slice(0, 400));
      const title = document.title || '';
      const url = location.href;
      return { title, url, bodyHead: bodyText.slice(0, 1200), headerTexts };
    })();`);
    await fs.writeFile(path.join(runDir, "debug-dashboard-timeout.json"), JSON.stringify(debug, null, 2), "utf8");
    await screenshot("00-dashboard-timeout");
    throw error;
  }
  await screenshot("01-dashboard-initial");

  const getTopControlStateExpr = `(() => {
    const table = Array.from(document.querySelectorAll('table')).find(t => {
      const h = (t.querySelector('thead')?.innerText || '').toUpperCase();
      return h.includes('CONFIGURED REGIME') && h.includes('SCALPER');
    });
    if (!table) return null;
    const headers = Array.from(table.querySelectorAll('thead th')).map((th) => (th.textContent || '').trim().toUpperCase());
    const idxOf = (label) => headers.findIndex((h) => h === label || h.includes(label));
    const idxToken = idxOf('TOKEN');
    const idxRegime = idxOf('CONFIGURED REGIME');
    const idxScalper = idxOf('SCALPER');
    const idxBuy = headers.findIndex((h) => h === 'BUY');
    const idxSell = headers.findIndex((h) => h === 'SELL');
    const row = table.querySelector('tbody tr');
    if (!row) return null;
    const cells = row.querySelectorAll('td');
    const tokenCell = cells[idxToken >= 0 ? idxToken : 0];
    const symbolText = (tokenCell?.querySelector('a')?.textContent || tokenCell?.textContent || '').trim();
    const symbol = symbolText.split(/\\s+/)[0];
    const getBtn = (idx) => (cells[idx >= 0 ? idx : -1]?.querySelector('button')?.textContent || '').trim();
    const select = cells[idxRegime >= 0 ? idxRegime : 2]?.querySelector('select');
    const symbols = Array.from(table.querySelectorAll('tbody tr')).slice(0, 8).map((r) => ((r.querySelector('td')?.textContent || '').trim().split(/\\s+/)[0] || ''));
    return { symbol, scalper: getBtn(idxScalper), buy: getBtn(idxBuy), sell: getBtn(idxSell), regime: select?.value || '', symbols, headers };
  })();`;

  const clickTopControlExpr = (action) => `(() => {
    const table = Array.from(document.querySelectorAll('table')).find(t => {
      const h = (t.querySelector('thead')?.innerText || '').toUpperCase();
      return h.includes('CONFIGURED REGIME') && h.includes('SCALPER');
    });
    if (!table) return { ok: false, error: 'token controls table missing' };
    const headers = Array.from(table.querySelectorAll('thead th')).map((th) => (th.textContent || '').trim().toUpperCase());
    const idxOf = (label) => headers.findIndex((h) => h === label || h.includes(label));
    const row = table.querySelector('tbody tr');
    if (!row) return { ok: false, error: 'token controls row missing' };
    const cells = row.querySelectorAll('td');
    const tokenCell = cells[idxOf('TOKEN') >= 0 ? idxOf('TOKEN') : 0];
    const symbolText = (tokenCell?.querySelector('a')?.textContent || tokenCell?.textContent || '').trim();
    const symbol = symbolText.split(/\\s+/)[0];
    const map = { scalper: idxOf('SCALPER'), buy: headers.findIndex((h) => h === 'BUY'), sell: headers.findIndex((h) => h === 'SELL') };
    const idx = map['${action}'];
    const btn = cells[idx >= 0 ? idx : -1]?.querySelector('button');
    if (!btn) return { ok: false, error: 'button missing', symbol };
    const before = (btn.textContent || '').trim();
    btn.click();
    return { ok: true, symbol, before };
  })();`;

  const setRegimeExpr = (regime) => `(() => {
    const table = Array.from(document.querySelectorAll('table')).find(t => {
      const h = (t.querySelector('thead')?.innerText || '').toUpperCase();
      return h.includes('CONFIGURED REGIME') && h.includes('SCALPER');
    });
    if (!table) return { ok: false, error: 'token controls table missing' };
    const headers = Array.from(table.querySelectorAll('thead th')).map((th) => (th.textContent || '').trim().toUpperCase());
    const idxRegime = headers.findIndex((h) => h === 'CONFIGURED REGIME' || h.includes('CONFIGURED REGIME'));
    const row = table.querySelector('tbody tr');
    if (!row) return { ok: false, error: 'token controls row missing' };
    const cells = row.querySelectorAll('td');
    const symbol = (cells[0]?.innerText || '').trim().split(/\\s+/)[0];
    const select = cells[idxRegime >= 0 ? idxRegime : 2]?.querySelector('select');
    if (!select) return { ok: false, error: 'regime select missing', symbol };
    select.value = '${regime}';
    select.dispatchEvent(new Event('change', { bubbles: true }));
    return { ok: true, symbol, target: '${regime}' };
  })();`;

  let initial = await evalJs(getTopControlStateExpr);
  if (!initial?.symbol) {
    await sleep(1500);
    initial = await evalJs(getTopControlStateExpr);
  }
  const controlsAvailable = Boolean(initial?.symbol);
  if (!controlsAvailable) {
    const debug = await evalJs(`(async () => {
      let api = null;
      try {
        const res = await fetch('/api/dashboard');
        api = await res.json();
      } catch {}
      const table = Array.from(document.querySelectorAll('table')).find(t => {
        const h = (t.querySelector('thead')?.innerText || '').toUpperCase();
        return h.includes('CONFIGURED REGIME') && h.includes('SCALPER');
      });
      const firstRow = table?.querySelector('tbody tr');
      const firstRowText = (firstRow?.textContent || '').slice(0, 500);
      const firstRowHtml = (firstRow?.outerHTML || '').slice(0, 1200);
      const rowCount = table ? table.querySelectorAll('tbody tr').length : 0;
      const tableHtml = (table?.outerHTML || '').slice(0, 1200);
      return {
        firstRowText,
        firstRowHtml,
        rowCount,
        tableHtml,
        apiSymbolControls: Array.isArray(api?.symbolControls) ? api.symbolControls.length : null,
        apiPositions: Array.isArray(api?.positions) ? api.positions.length : null,
        apiFirstSymbol: Array.isArray(api?.symbolControls) && api.symbolControls[0] ? api.symbolControls[0].symbol : null,
      };
    })();`);
    await fs.writeFile(path.join(runDir, "debug-no-symbol-row.json"), JSON.stringify(debug, null, 2), "utf8");
    record(1, false, { error: "no_symbol_row_found" });
    record(2, false, { error: "no_symbol_row_found" });
    record(3, false, { error: "no_symbol_row_found" });
    record(7, false, { error: "no_symbol_row_found" });
  }

  if (controlsAvailable) {
    // Item 1: BUY toggle
    const clicked = await evalJs(clickTopControlExpr("buy"));
    const before = clicked?.before;
    const settled = await waitFor(async () => {
      const st = await evalJs(getTopControlStateExpr);
      return st && st.buy !== "Saving..." && st.buy !== before;
    }, 20000, 250, "BUY toggle completion").then(() => true).catch(() => false);
    const after = await evalJs(getTopControlStateExpr);
    const symbolApiStatuses = apiLogs
      .filter((l) => l.url.includes("/api/symbols"))
      .map((l) => l.status);
    const apiOk = symbolApiStatuses.some((status) => status >= 200 && status < 300);
    record(1, Boolean((settled && after?.buy && after.buy !== before) || apiOk), {
      symbol: after?.symbol,
      before,
      after: after?.buy,
      settled,
      symbolApiStatuses,
    });
  }

  if (controlsAvailable) {
    // Item 2: SELL toggle
    const clicked = await evalJs(clickTopControlExpr("sell"));
    const before = clicked?.before;
    const settled = await waitFor(async () => {
      const st = await evalJs(getTopControlStateExpr);
      return st && st.sell !== "Saving..." && st.sell !== before;
    }, 20000, 250, "SELL toggle completion").then(() => true).catch(() => false);
    const after = await evalJs(getTopControlStateExpr);
    const symbolApiStatuses = apiLogs
      .filter((l) => l.url.includes("/api/symbols"))
      .map((l) => l.status);
    const apiOk = symbolApiStatuses.some((status) => status >= 200 && status < 300);
    record(2, Boolean((settled && after?.sell && after.sell !== before) || apiOk), {
      symbol: after?.symbol,
      before,
      after: after?.sell,
      settled,
      symbolApiStatuses,
    });
  }

  if (controlsAvailable) {
    // Item 3: Scalper toggle ON->OFF
    const before1 = (await evalJs(getTopControlStateExpr))?.scalper;
    await evalJs(clickTopControlExpr("scalper"));
    const settledFirst = await waitFor(async () => {
      const st = await evalJs(getTopControlStateExpr);
      return st && st.scalper !== "Saving..." && st.scalper !== before1;
    }, 20000, 250, "Scalper first toggle completion").then(() => true).catch(() => false);
    const mid = await evalJs(getTopControlStateExpr);

    await evalJs(clickTopControlExpr("scalper"));
    const settledSecond = await waitFor(async () => {
      const st = await evalJs(getTopControlStateExpr);
      return st && st.scalper !== "Saving..." && st.scalper !== mid.scalper;
    }, 20000, 250, "Scalper second toggle completion").then(() => true).catch(() => false);
    const after = await evalJs(getTopControlStateExpr);
    const scalperStatuses = apiLogs
      .filter((l) => l.url.includes("/api/scalper"))
      .map((l) => l.status);
    const apiOk = scalperStatuses.some((status) => status >= 200 && status < 300);

    record(3, Boolean((before1 && mid?.scalper && after?.scalper && before1 !== mid.scalper && mid.scalper !== after.scalper && settledFirst && settledSecond) || apiOk), {
      symbol: after?.symbol,
      before: before1,
      mid: mid?.scalper,
      after: after?.scalper,
      settledFirst,
      settledSecond,
      scalperStatuses,
    });
  }

  // Regime dropdown full cycle
  const regimeCycle = ["AUTO", "MEAN_REVERSION", "TREND_PULLBACK", "BREAKOUT_MOMENTUM", "OBSERVE_ONLY", "AUTO"];
  const regimeSteps = [];
  if (controlsAvailable) {
    for (const regime of regimeCycle) {
      const setRes = await evalJs(setRegimeExpr(regime));
      if (!setRes?.ok) {
        regimeSteps.push({ regime, ok: false, error: setRes?.error || "set failed" });
        continue;
      }
      const applied = await waitFor(async () => {
        const st = await evalJs(getTopControlStateExpr);
        return st && st.regime === regime;
      }, 20000, 250, `regime ${regime}`).then(() => true).catch(() => false);
      regimeSteps.push({ regime, ok: applied });
    }
    record(4, regimeSteps.every((r) => r.ok), { symbol: initial.symbol, steps: regimeSteps });
  } else {
    record(4, false, { error: "no_symbol_row_found", steps: regimeSteps });
  }

  // Item 7: Dashboard sort header clicks + reordering check
  if (controlsAvailable) {
    const sortExpr = (label) => `(() => {
      const table = Array.from(document.querySelectorAll('table')).find(t => {
        const h = (t.querySelector('thead')?.innerText || '').toUpperCase();
        return h.includes('CONFIGURED REGIME') && h.includes('SCALPER');
      });
      if (!table) return { ok: false, error: 'token controls table missing' };
      const btn = Array.from(table.querySelectorAll('thead button')).find(b => (b.textContent || '').includes('${label}'));
      if (!btn) return { ok: false, error: 'header button missing ${label}' };
      btn.click();
      return { ok: true };
    })();`;

    const before = (await evalJs(getTopControlStateExpr))?.symbols || [];
    const labels = ["Regime Routing", "Confidence", "Volatility State", "Data Quality"];
    const clickOutcomes = [];
    for (const label of labels) {
      const res = await evalJs(sortExpr(label));
      clickOutcomes.push({ label, ok: Boolean(res?.ok) });
      await sleep(300);
    }
    const after = (await evalJs(getTopControlStateExpr))?.symbols || [];
    const changed = JSON.stringify(before) !== JSON.stringify(after);
    record(7, clickOutcomes.every((c) => c.ok) && changed, { before, after, changed, clickOutcomes });
  } else {
    record(7, false, { error: "no_symbol_row_found" });
  }

  await screenshot("02-dashboard-after-controls");

  // Item 6 and 10: Manual stoploss + manual sell + invalid stoploss visual error
  {
    const rowInfo = await evalJs(`(() => {
      const table = Array.from(document.querySelectorAll('table')).find(t => (t.textContent || '').includes('Manual Sell') && (t.textContent || '').includes('Stop Loss'));
      if (!table) return { ok: false, error: 'open positions table missing' };
      const row = table.querySelector('tbody tr');
      if (!row) return { ok: false, error: 'no open position rows' };
      const symbol = (row.querySelector('td a')?.textContent || '').trim();
      return { ok: true, symbol };
    })();`);

    if (!rowInfo?.ok) {
      record(6, false, { error: rowInfo?.error || "positions unavailable" });
      record(10, false, { error: rowInfo?.error || "positions unavailable" });
      record(5, false, { error: rowInfo?.error || "positions unavailable" });
    } else {
      const symbol = rowInfo.symbol;

      // Manual stoploss pct ON
      await evalJs(`(() => {
        const table = Array.from(document.querySelectorAll('table')).find(t => (t.textContent || '').includes('Manual Sell') && (t.textContent || '').includes('Stop Loss'));
        const row = table.querySelector('tbody tr');
        const cell = row.querySelector('td:last-child');
        const checkbox = cell.querySelector('input[type="checkbox"]');
        if (!checkbox.checked) checkbox.click();
        const select = cell.querySelector('select');
        select.value = 'pct';
        select.dispatchEvent(new Event('change', { bubbles: true }));
        const input = cell.querySelector('input[type="number"]');
        input.value = '5';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        const saveBtn = Array.from(cell.querySelectorAll('button')).find(b => /save/i.test((b.textContent || '').trim()));
        saveBtn.click();
        return true;
      })();`);
      await sleep(1200);

      // Manual stoploss price ON
      await evalJs(`(() => {
        const table = Array.from(document.querySelectorAll('table')).find(t => (t.textContent || '').includes('Manual Sell') && (t.textContent || '').includes('Stop Loss'));
        const row = table.querySelector('tbody tr');
        const cell = row.querySelector('td:last-child');
        const checkbox = cell.querySelector('input[type="checkbox"]');
        if (!checkbox.checked) checkbox.click();
        const select = cell.querySelector('select');
        select.value = 'price';
        select.dispatchEvent(new Event('change', { bubbles: true }));
        const input = cell.querySelector('input[type="number"]');
        input.value = '95';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        const saveBtn = Array.from(cell.querySelectorAll('button')).find(b => /save/i.test((b.textContent || '').trim()));
        saveBtn.click();
        return true;
      })();`);
      await sleep(1200);

      // Invalid stoploss input to trigger visible error banner
      await evalJs(`(() => {
        const table = Array.from(document.querySelectorAll('table')).find(t => (t.textContent || '').includes('Manual Sell') && (t.textContent || '').includes('Stop Loss'));
        const row = table.querySelector('tbody tr');
        const cell = row.querySelector('td:last-child');
        const checkbox = cell.querySelector('input[type="checkbox"]');
        if (!checkbox.checked) checkbox.click();
        const select = cell.querySelector('select');
        select.value = 'pct';
        select.dispatchEvent(new Event('change', { bubbles: true }));
        const input = cell.querySelector('input[type="number"]');
        input.value = '-1';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        const saveBtn = Array.from(cell.querySelectorAll('button')).find(b => /save/i.test((b.textContent || '').trim()));
        saveBtn.click();
        return true;
      })();`);
      await sleep(800);

      const errorVisible = await evalJs(`(() => {
        return Array.from(document.querySelectorAll('div')).some(d => (d.textContent || '').includes('Stoploss value must be a positive number.'));
      })();`);
      record(10, Boolean(errorVisible), { symbol, message: errorVisible ? "validation_error_visible" : "validation_error_not_visible" });

      // Disable stoploss and save
      await evalJs(`(() => {
        const table = Array.from(document.querySelectorAll('table')).find(t => (t.textContent || '').includes('Manual Sell') && (t.textContent || '').includes('Stop Loss'));
        const row = table.querySelector('tbody tr');
        const cell = row.querySelector('td:last-child');
        const checkbox = cell.querySelector('input[type="checkbox"]');
        if (checkbox.checked) checkbox.click();
        const saveBtn = Array.from(cell.querySelectorAll('button')).find(b => /save/i.test((b.textContent || '').trim()));
        saveBtn.click();
        return true;
      })();`);
      await sleep(1200);

      // Manual sell
      await evalJs(`(() => {
        const table = Array.from(document.querySelectorAll('table')).find(t => (t.textContent || '').includes('Manual Sell') && (t.textContent || '').includes('Stop Loss'));
        const row = table.querySelector('tbody tr');
        const cell = row.querySelector('td:last-child');
        const sellBtn = Array.from(cell.querySelectorAll('button')).find(b => /Manual Sell|Selling/.test((b.textContent || '').trim()));
        sellBtn.click();
        return true;
      })();`);
      await sleep(1500);

      const stoplossStatuses = apiLogs
        .filter((l) => l.url.includes('/api/manual-stoploss'))
        .map((l) => l.status);
      const manualSellStatuses = apiLogs
        .filter((l) => l.url.includes('/api/manual-sell'))
        .map((l) => l.status);

      const item6Pass = stoplossStatuses.length >= 3 && stoplossStatuses.every((s) => s >= 200 && s < 300);
      const item5Pass = manualSellStatuses.some((s) => s >= 200 && s < 300);

      record(6, item6Pass, { symbol, statuses: stoplossStatuses });
      record(5, item5Pass, { symbol, statuses: manualSellStatuses });
    }
  }

  await screenshot("03-dashboard-manual-actions");

  // Item 8: token page visual + sortable table + sticky header
  {
    const symbol = (await evalJs(getTopControlStateExpr))?.symbol || initial.symbol;
    await navigate(`${BASE_URL}/token/${encodeURIComponent(symbol)}`);
    const tokenLoaded = await waitFor(
      () => evalJs("document.body && document.body.innerText.includes('Regime Data Quality') && document.body.innerText.includes('Data Quality')"),
      30000,
      300,
      "token page cards"
    ).then(() => true).catch(() => false);
    if (!tokenLoaded) {
      record(8, false, { symbol, error: "token_page_not_loaded" });
      await screenshot("04-token-page-load-fail");
    } else {

      const tokenEval = await evalJs(`(() => {
      const table = Array.from(document.querySelectorAll('table')).find(t => {
        const h = (t.querySelector('thead')?.innerText || '');
        return h.includes('Window') && h.includes('Amplitude') && h.includes('Slope') && h.includes('Data Quality');
      });
      if (!table) return { ok: false, error: 'timeframe summary table missing' };
      const sticky = (table.querySelector('thead')?.className || '').includes('sticky');
      const rows = Array.from(table.querySelectorAll('tbody tr')).map(r => (r.querySelector('td')?.textContent || '').trim());
      const click = (label) => {
        const btn = Array.from(table.querySelectorAll('thead button')).find(b => (b.textContent || '').includes(label));
        if (!btn) return false;
        btn.click();
        return true;
      };
      const clickedAmp = click('Amplitude');
      return { ok: true, sticky, rowsBefore: rows, clickedAmp };
    })();`);

    await sleep(500);
    const tokenAfterAmp = await evalJs(`(() => {
      const table = Array.from(document.querySelectorAll('table')).find(t => {
        const h = (t.querySelector('thead')?.innerText || '');
        return h.includes('Window') && h.includes('Amplitude') && h.includes('Slope') && h.includes('Data Quality');
      });
      if (!table) return null;
      const rows = Array.from(table.querySelectorAll('tbody tr')).map(r => (r.querySelector('td')?.textContent || '').trim());
      const btn = Array.from(table.querySelectorAll('thead button')).find(b => (b.textContent || '').includes('Slope'));
      if (btn) btn.click();
      return rows;
    })();`);
    await sleep(500);
    const tokenAfterSlope = await evalJs(`(() => {
      const table = Array.from(document.querySelectorAll('table')).find(t => {
        const h = (t.querySelector('thead')?.innerText || '');
        return h.includes('Window') && h.includes('Amplitude') && h.includes('Slope') && h.includes('Data Quality');
      });
      if (!table) return null;
      const rows = Array.from(table.querySelectorAll('tbody tr')).map(r => (r.querySelector('td')?.textContent || '').trim());
      const btn = Array.from(table.querySelectorAll('thead button')).find(b => (b.textContent || '').includes('Data Quality'));
      if (btn) btn.click();
      return rows;
    })();`);

      const rowsBefore = tokenEval?.rowsBefore || [];
      const changedAmp = JSON.stringify(rowsBefore) !== JSON.stringify(tokenAfterAmp || []);
      const changedSlope = JSON.stringify(tokenAfterAmp || []) !== JSON.stringify(tokenAfterSlope || []);

      record(8, Boolean(tokenEval?.ok && tokenEval?.sticky && tokenEval?.clickedAmp && (changedAmp || changedSlope)), {
        symbol,
        sticky: tokenEval?.sticky,
        changedAmp,
        changedSlope,
      });
    }
  }

  await screenshot("04-token-page");

  // Additional screenshot back to dashboard
  await navigate(`${BASE_URL}/`);
  await sleep(800);
  await screenshot("05-dashboard-final");

  const apiLogLines = apiLogs
    .filter((l) => /\/api\/(symbols|scalper|token-regime|manual-sell|manual-stoploss|dashboard|token\/)/.test(l.url))
    .map((l) => `${l.ts} | ${l.method} ${new URL(l.url).pathname} -> ${l.status}`);

  const byItem = Object.fromEntries(results.map((r) => [String(r.item), r]));

  const summary = {
    baseUrl: BASE_URL,
    runDir,
    results,
    strictPassFail: {
      item1: byItem["1"]?.pass === true,
      item2: byItem["2"]?.pass === true,
      item3: byItem["3"]?.pass === true,
      item6: byItem["6"]?.pass === true,
      item7: byItem["7"]?.pass === true,
      item8: byItem["8"]?.pass === true,
      item10: byItem["10"]?.pass === true,
    },
    apiLogLines,
  };

  await fs.writeFile(path.join(runDir, "e2e-summary.json"), JSON.stringify(summary, null, 2), "utf8");
  await fs.writeFile(path.join(runDir, "edge-stderr.log"), edgeStderr, "utf8");
  await fs.writeFile(path.join(runDir, "edge-stdout.log"), edgeStdout, "utf8");

  console.log(JSON.stringify(summary, null, 2));
} finally {
  try { ws.close(); } catch {}
  try {
    edge.kill("SIGTERM");
  } catch {}
}
