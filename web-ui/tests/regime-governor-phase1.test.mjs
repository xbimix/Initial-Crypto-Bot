import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const dashboardRoutePath = resolve("src/app/api/dashboard/route.ts");
const tokenRoutePath = resolve("src/app/api/token/[symbol]/route.ts");
const dashboardPagePath = resolve("src/app/components/RevbotDashboard.tsx");
const tokenRegimeApiRoutePath = resolve("src/app/api/token-regime/route.ts");

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

await run("dashboard payload exposes configured regime per token", async () => {
  const source = await readFile(dashboardRoutePath, "utf8");
  assert.match(source, /token_regimes/);
  assert.match(source, /parseTokenRegimeMap/);
  assert.match(source, /configuredRegime\s*,/);
});

await run("token detail API surfaces configured regime read-only", async () => {
  const source = await readFile(tokenRoutePath, "utf8");
  assert.match(source, /configuredRegime/);
  assert.match(source, /configuredRegime:\s*control\?\.configuredRegime\s*\?\?\s*"MEAN_REVERSION"/);
});

await run("dashboard token controls uses single wired regime dropdown + mutation path", async () => {
  const source = await readFile(dashboardPagePath, "utf8");
  assert.match(source, /TOKEN_REGIME_OPTIONS/);
  assert.match(source, /setTokenRegime/);
  assert.match(source, /fetch\("\/api\/token-regime"/);
  assert.match(source, /value=\{control\.configuredRegime\}/);
});

await run("token regime API route proxies backend and fallback path", async () => {
  const source = await readFile(tokenRegimeApiRoutePath, "utf8");
  assert.match(source, /BACKEND.*127\.0\.0\.1:8001/);
  assert.match(source, /fetch\(`\$\{BACKEND\}\/token-regime`/);
  assert.match(source, /updateTokenRegimeLocal/);
});
