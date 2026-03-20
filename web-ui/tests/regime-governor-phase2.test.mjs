import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { analyzeRegimeGovernor } from "../src/app/lib/regimeGovernorAnalyzer.mjs";

function run(name, fn) {
  try {
    fn();
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    console.error(error);
    process.exitCode = 1;
  }
}

function buildSeries({
  startEpoch = 1_770_000_000,
  points = 1400,
  stepSeconds = 300,
  generator,
}) {
  const rows = [];
  for (let index = 0; index < points; index += 1) {
    rows.push({
      tsEpoch: startEpoch + (index * stepSeconds),
      price: generator(index),
    });
  }
  return rows;
}

run("regime analyzer outputs advisory shape with confidence fields", () => {
  const points = buildSeries({
    generator: (index) => 100 + (Math.sin(index / 7) * 3.8),
  });
  const nowEpoch = points[points.length - 1].tsEpoch;
  const result = analyzeRegimeGovernor({
    symbol: "TEST-USD",
    pricePoints: points,
    latestSnapshot: { spreadBps: 20, quality: "ok" },
    nowEpoch,
  });

  assert.equal(result.symbol, "TEST-USD");
  assert.ok(typeof result.suggestedRegime === "string");
  assert.ok(Number.isFinite(result.confidenceScore));
  assert.ok(result.confidenceScore >= 0 && result.confidenceScore <= 100);
  assert.ok(["LOW", "MEDIUM", "HIGH"].includes(result.confidenceLabel));
  assert.ok(typeof result.explanation === "string");
  assert.ok(typeof result.components?.structureBias === "string");
  assert.ok(Number.isFinite(result.componentScores?.trend_score));
  assert.ok(Number.isFinite(result.componentScores?.range_score));
  assert.ok(Number.isFinite(result.componentScores?.breakout_score));
  assert.ok(Number.isFinite(result.componentScores?.mixed_score));
  assert.ok(Number.isFinite(result.stability_score));
  assert.ok(result.stability_score >= 0 && result.stability_score <= 100);
  assert.equal(result.detectionSource, "advisory_multitimeframe");
  assert.ok(Number.isFinite(result.analysisAnchorEpoch));
  assert.ok(typeof result.timeframeSummary?.["1h"] === "object");
  assert.ok(typeof result.data_quality?.status === "string");
  assert.ok(typeof result.timeframeSummary?.["1h"]?.data_quality?.status === "string");
});

run("regime analyzer degrades gracefully with thin history", () => {
  const points = [
    { tsEpoch: 1_770_000_000, price: 100 },
    { tsEpoch: 1_770_000_180, price: 100.1 },
    { tsEpoch: 1_770_000_360, price: 99.9 },
  ];
  const result = analyzeRegimeGovernor({
    symbol: "THIN-USD",
    pricePoints: points,
    latestSnapshot: null,
    nowEpoch: points[points.length - 1].tsEpoch,
  });

  assert.equal(result.suggestedRegime, "MIXED_OR_UNCLEAR");
  assert.ok(Number.isFinite(result.confidenceScore));
  assert.ok(result.timeframeSummary["1h"].insufficientData === true);
  assert.ok(typeof result.timeframeSummary["1h"].insufficientReasonCode === "string");
});

run("dashboard and token routes expose detected regime advisory fields", async () => {
  const dashboardRoutePath = resolve("src/app/api/dashboard/route.ts");
  const tokenRoutePath = resolve("src/app/api/token/[symbol]/route.ts");
  const tokenPagePath = resolve("src/app/token/[symbol]/page.tsx");

  const [dashboardSource, tokenRouteSource, tokenPageSource] = await Promise.all([
    readFile(dashboardRoutePath, "utf8"),
    readFile(tokenRoutePath, "utf8"),
    readFile(tokenPagePath, "utf8"),
  ]);

  assert.match(dashboardSource, /analyzeRegimeGovernor/);
  assert.match(dashboardSource, /detectedRegime/);
  assert.match(dashboardSource, /detectedRegimeConfidenceLabel/);
  assert.match(dashboardSource, /detectedRegimeConfidenceScore/);
  assert.match(dashboardSource, /detectionSource/);
  assert.match(dashboardSource, /detectionTimestampEpoch/);
  assert.match(tokenRouteSource, /regimeAdvisory/);
  assert.match(tokenRouteSource, /detectedRegimeExplanation/);
  assert.match(tokenRouteSource, /detectionSource/);
  assert.match(tokenPageSource, /Regime Analysis/);
  assert.match(tokenPageSource, /detectedRegimeConfidenceLabel/);
});
