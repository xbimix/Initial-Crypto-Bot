import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const pagePath = resolve("src/app/token/[symbol]/page.tsx");
const routePath = resolve("src/app/api/token/[symbol]/route.ts");
const analyzerPath = resolve("src/app/lib/waveZoneAnalyzer.mjs");

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

await run("token detail page renders Wave Zone Analyzer section and timeframe labels", async () => {
  const pageSource = await readFile(pagePath, "utf8");

  assert.match(pageSource, /Wave Zone Analyzer/);
  assert.match(pageSource, /weighted_low_revisit_likelihood_pct|Weighted Low Revisit/);
  assert.match(pageSource, /weighted_high_revisit_likelihood_pct|Weighted High Revisit/);
  assert.match(pageSource, /LOW MAGNET/);
  assert.match(pageSource, /HIGH MAGNET/);
  assert.match(pageSource, /BALANCED/);
  assert.match(pageSource, /Insufficient data/);
  assert.match(pageSource, /"1h", "4h", "8h", "16h", "24h", "3d", "7d"/);
});

await run("token API payload includes waveZoneAnalyzer advisory block", async () => {
  const routeSource = await readFile(routePath, "utf8");
  const analyzerSource = await readFile(analyzerPath, "utf8");

  assert.match(routeSource, /analyzeWaveZones/);
  assert.match(routeSource, /waveZoneAnalyzer/);
  assert.match(analyzerSource, /data_quality_note|data quality note/i);
});
