import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const pagePath = resolve("src/app/token/[symbol]/page.tsx");
const routePath = resolve("src/app/api/token/[symbol]/route.ts");
const analyzerPath = resolve("src/app/lib/waveZoneAnalyzer.mjs");
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

await run("token detail page renders Wave Zone Analyzer section and timeframe labels", async () => {
  const pageSource = await readFile(pagePath, "utf8");

  assert.match(pageSource, /Wave Zone Analyzer/);
  assert.match(pageSource, /weighted_low_revisit_likelihood_pct|Weighted Low Revisit/);
  assert.match(pageSource, /weighted_high_revisit_likelihood_pct|Weighted High Revisit/);
  assert.match(pageSource, /LOW MAGNET/);
  assert.match(pageSource, /HIGH MAGNET/);
  assert.match(pageSource, /BALANCED/);
  assert.match(pageSource, /Insufficient data/);
  assert.match(pageSource, /insufficient_reason_code|Code:/);
  assert.match(pageSource, /latest_snapshot_age_minutes|Latest snapshot age/);
  assert.match(pageSource, /Rolling Symbol Rotation Monitor/);
  assert.match(pageSource, /Volatility Opportunity/);
  assert.match(pageSource, /Indicator Engine/);
  assert.match(pageSource, /Why No Trade/);
  assert.match(pageSource, /volatilityOpportunity|volatility opportunity/i);
  assert.match(pageSource, /Sort Score|LOW MAGNET|HIGH MAGNET/);
  assert.match(pageSource, /Capital Trap Risk/);
  assert.match(pageSource, /"1h", "4h", "8h", "16h", "24h", "3d", "7d"/);
  assert.match(pageSource, /Window/);
  assert.match(pageSource, /Structure/);
  assert.match(pageSource, /Amplitude/);
  assert.match(pageSource, /Slope/);
  assert.match(pageSource, /Median High/);
  assert.match(pageSource, /Median Low/);
  assert.match(pageSource, /Sample/);
  assert.match(pageSource, /Data Quality/);
});

await run("token API payload includes waveZoneAnalyzer advisory block", async () => {
  const routeSource = await readFile(routePath, "utf8");
  const analyzerSource = await readFile(analyzerPath, "utf8");
  const dashboardRouteSource = await readFile(dashboardRoutePath, "utf8");
  const dashboardPageSource = await readFile(dashboardPagePath, "utf8");

  assert.match(routeSource, /analyzeWaveZones/);
  assert.match(routeSource, /waveZoneAnalyzer/);
  assert.match(routeSource, /readSnapshotHistory\(/);
  assert.match(routeSource, /historySource|rotated_logs|bot_log_tail_fallback/);
  assert.match(routeSource, /nowEpoch:\s*analysisAnchorEpoch/);
  assert.match(routeSource, /wallClockEpoch/);
  assert.match(routeSource, /rotationMonitor/);
  assert.match(routeSource, /volatilityOpportunity:\s*\{/);
  assert.match(routeSource, /buildIndicatorBundle|indicators:/);
  assert.match(routeSource, /volatilityOpportunityScorePct/);
  assert.match(routeSource, /rotationShortTermScore|rotationMediumTermScore/);
  assert.match(analyzerSource, /data_quality_note|data quality note/i);
  assert.match(analyzerSource, /insufficient_reason_code/);
  assert.match(analyzerSource, /stale_snapshot_history/);
  assert.match(dashboardRouteSource, /rotationShortTermScore|rotationStatus|buildSymbolRotationAdvisory/);
  assert.match(dashboardRouteSource, /volatilityOpportunityScore|highOpportunitySymbolCount|topVolatilityOpportunitySymbols/);
  assert.match(dashboardPageSource, /Rolling Symbol Rotation|rotationStatusStyle|Trap Risk/);
  assert.match(dashboardPageSource, /Volatility Opportunity Radar|Sort Volatility|volatilityOpportunityScore/);
  assert.match(dashboardPageSource, /Regime Routing|Suggested Regime V2|Detected \(Legacy\/Shadow\)/);
  assert.match(dashboardPageSource, /Volatility State/);
  assert.match(dashboardPageSource, /Data Quality/);
  assert.match(dashboardPageSource, /setControlSort/);
  assert.match(dashboardPageSource, /sticky top-0/);
});
