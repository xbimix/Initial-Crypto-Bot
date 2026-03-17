import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const universePagePath = resolve("src/app/universe/page.tsx");
const universeApiPath = resolve("src/app/api/revolut-universe/route.ts");
const accountApiPath = resolve("src/app/api/revolut-account/route.ts");
const universeTrackApiPath = resolve("src/app/api/universe-track/route.ts");
const dashboardRoutePath = resolve("src/app/api/dashboard/route.ts");
const dashboardPagePath = resolve("src/app/components/RevbotDashboard.tsx");

async function run(name, fn) {
  try {
    await fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    console.error(error);
    process.exitCode = 1;
  }
}

await run("universe manager page exists with tracked toggle mutation", async () => {
  const source = await readFile(universePagePath, "utf8");
  assert.match(source, /Universe Manager/);
  assert.match(source, /fetch\((`|")\/api\/revolut-universe/);
  assert.match(source, /fetch\((`|")\/api\/revolut-account/);
  assert.match(source, /fetch\("\/api\/universe-track"/);
  assert.match(source, /Current Price/);
  assert.match(source, /24H %/);
  assert.match(source, /toggleSort/);
  assert.match(source, /USD \+ EUR/);
  assert.match(source, /USD only/);
  assert.match(source, /EUR only/);
});

await run("revolut universe api route proxies backend endpoint", async () => {
  const source = await readFile(universeApiPath, "utf8");
  assert.match(source, /127\.0\.0\.1:8001/);
  assert.match(source, /\/revolut-universe/);
});

await run("revolut account api route proxies backend endpoint", async () => {
  const source = await readFile(accountApiPath, "utf8");
  assert.match(source, /127\.0\.0\.1:8001/);
  assert.match(source, /\/revolut-account/);
});

await run("universe track api route uses mutating auth and local fallback", async () => {
  const source = await readFile(universeTrackApiPath, "utf8");
  assert.match(source, /requireMutatingAuth/);
  assert.match(source, /updateUniverseTrackLocal/);
  assert.match(source, /\/universe-track/);
});

await run("dashboard payload exposes tradingEnabled separation", async () => {
  const source = await readFile(dashboardRoutePath, "utf8");
  assert.match(source, /tradingEnabled/);
  assert.match(source, /config\.trading_enabled/);
});

await run("dashboard UI renders trading armed\/disarmed state", async () => {
  const source = await readFile(dashboardPagePath, "utf8");
  assert.match(source, /tradingEnabled/);
  assert.match(source, /Trading armed/);
  assert.match(source, /Trading disarmed/);
});
