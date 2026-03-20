import assert from "node:assert/strict";
import {
  RADAR_WINDOWS,
  mapOpportunityLabel,
  analyzeVolatilityOpportunity,
} from "../src/app/lib/volatilityOpportunityRadar.mjs";

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
  points = 420,
  stepSeconds = 120,
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

run("high stretch + volatility fixture scores above mild low-vol fixture", () => {
  const panicFlush = buildSeries({
    points: 520,
    stepSeconds: 90,
    generator: (index) => {
      if (index < 420) {
        return 100 + (Math.sin(index / 15) * 0.6);
      }
      const drift = (index - 420) * 0.07;
      const shake = Math.sin(index / 2) * 1.7;
      return Math.max(80, 99 - drift + shake);
    },
  });
  const slowSideways = buildSeries({
    points: 520,
    stepSeconds: 90,
    generator: (index) => 100 + (Math.sin(index / 17) * 0.25),
  });

  const flushNow = panicFlush[panicFlush.length - 1].tsEpoch;
  const sideNow = slowSideways[slowSideways.length - 1].tsEpoch;
  const flush = analyzeVolatilityOpportunity({
    symbol: "FLUSH-USD",
    pricePoints: panicFlush,
    latestSnapshot: { spreadBps: 22, quality: "ok" },
    nowEpoch: flushNow,
    wallClockEpoch: flushNow,
  });
  const mild = analyzeVolatilityOpportunity({
    symbol: "SIDE-USD",
    pricePoints: slowSideways,
    latestSnapshot: { spreadBps: 20, quality: "ok" },
    nowEpoch: sideNow,
    wallClockEpoch: sideNow,
  });

  assert.equal(flush.insufficient_data, false);
  assert.equal(mild.insufficient_data, false);
  assert.ok(Number(flush.score) > Number(mild.score));
});

run("insufficient data path returns explicit reason and counts", () => {
  const thin = [
    { tsEpoch: 1_770_000_000, price: 100 },
    { tsEpoch: 1_770_000_120, price: 99.9 },
    { tsEpoch: 1_770_000_240, price: 100.1 },
  ];
  const result = analyzeVolatilityOpportunity({
    symbol: "THIN-USD",
    pricePoints: thin,
    latestSnapshot: null,
    nowEpoch: thin[thin.length - 1].tsEpoch,
    wallClockEpoch: thin[thin.length - 1].tsEpoch,
  });

  assert.equal(result.insufficient_data, true);
  assert.equal(result.insufficient_reason_code, "insufficient_point_count");
  assert.ok(typeof result.insufficient_reason_message === "string");
  assert.equal(result.observed_point_count, thin.length);
});

run("label mapping covers low/medium/high thresholds", () => {
  assert.equal(mapOpportunityLabel(5), "LOW");
  assert.equal(mapOpportunityLabel(40), "MEDIUM");
  assert.equal(mapOpportunityLabel(70), "HIGH");
  assert.equal(mapOpportunityLabel(null), null);
});

run("output shape has stable ranges when sufficient", () => {
  const points = buildSeries({
    points: 700,
    stepSeconds: 60,
    generator: (index) => 75 + (Math.sin(index / 8) * 1.8) + (Math.sin(index / 31) * 0.4),
  });
  const nowEpoch = points[points.length - 1].tsEpoch;
  const result = analyzeVolatilityOpportunity({
    symbol: "RANGE-USD",
    pricePoints: points,
    latestSnapshot: { spreadBps: 18, quality: "ok" },
    nowEpoch,
    wallClockEpoch: nowEpoch,
  });

  assert.equal(result.symbol, "RANGE-USD");
  assert.equal(typeof result.reason, "string");
  assert.ok(result.observed_history_span_minutes > 0);
  assert.ok(result.window_coverage.total_windows === RADAR_WINDOWS.length);
  assert.ok(typeof result.volatility_state === "string");
  assert.ok(typeof result.data_quality?.status === "string");
  if (!result.insufficient_data) {
    assert.ok(Number(result.score) >= 0);
    assert.ok(Number(result.score) <= 100);
    assert.ok(Number(result.stretch_score) >= 0);
    assert.ok(Number(result.stretch_score) <= 100);
    assert.ok(Number(result.volatility_spike_score) >= 0);
    assert.ok(Number(result.volatility_spike_score) <= 100);
    assert.ok(Number(result.bounce_context_score) >= 0);
    assert.ok(Number(result.bounce_context_score) <= 100);
    assert.ok(["GOOD", "PARTIAL", "STALE", "INSUFFICIENT"].includes(result.data_quality.status));
  }
});
