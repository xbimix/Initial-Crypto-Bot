import assert from "node:assert/strict";
import {
  TIMEFRAME_CONFIG,
  buildCandlesFromSnapshots,
  detectSwingPivots,
  clusterPivotZones,
  countZoneTouches,
  analyzeWaveZones,
} from "../src/app/lib/waveZoneAnalyzer.mjs";

function buildSeries({
  startEpoch = 1_770_000_000,
  points = 400,
  stepSeconds = 300,
  generator,
}) {
  const output = [];
  for (let index = 0; index < points; index += 1) {
    output.push({
      tsEpoch: startEpoch + (index * stepSeconds),
      price: generator(index),
    });
  }
  return output;
}

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

run("pivot detection identifies swing highs/lows from candles", () => {
  const candles = [
    { tsEpoch: 1, open: 9, high: 10, low: 9, close: 9.5 },
    { tsEpoch: 2, open: 9.5, high: 11, low: 8, close: 10 },
    { tsEpoch: 3, open: 10, high: 12, low: 7, close: 11 },
    { tsEpoch: 4, open: 11, high: 13, low: 6, close: 12 },
    { tsEpoch: 5, open: 12, high: 15, low: 7, close: 13 },
    { tsEpoch: 6, open: 13, high: 13, low: 8, close: 12 },
    { tsEpoch: 7, open: 12, high: 12, low: 9, close: 11 },
    { tsEpoch: 8, open: 11, high: 11, low: 10, close: 10.5 },
    { tsEpoch: 9, open: 10.5, high: 10, low: 11, close: 10.7 },
  ];

  const pivots = detectSwingPivots(candles, 2);
  assert.equal(pivots.highs.length, 1);
  assert.equal(pivots.lows.length, 1);
  assert.equal(pivots.highs[0].index, 4);
  assert.equal(pivots.lows[0].index, 3);
});

run("zone clustering merges nearby pivots into support/resistance zones", () => {
  const pivots = [
    { price: 100.0, tsEpoch: 1, index: 1, type: "low" },
    { price: 100.2, tsEpoch: 2, index: 2, type: "low" },
    { price: 100.35, tsEpoch: 3, index: 3, type: "low" },
    { price: 101.8, tsEpoch: 4, index: 4, type: "low" },
  ];
  const zones = clusterPivotZones(pivots, 0.5);
  assert.equal(zones.length, 2);
  assert.equal(zones[0].pivot_count, 3);
  assert.equal(zones[1].pivot_count, 1);
});

run("touch counting does not overcount contiguous in-zone candles", () => {
  const zone = { zone_min: 99, zone_max: 101, zone_center: 100 };
  const candles = [
    { tsEpoch: 1, high: 103, low: 102 },
    { tsEpoch: 2, high: 101.5, low: 100.5 },
    { tsEpoch: 3, high: 100.4, low: 99.8 },
    { tsEpoch: 4, high: 101.2, low: 100.2 },
    { tsEpoch: 5, high: 102.0, low: 101.2 },
    { tsEpoch: 6, high: 101.1, low: 100.9 },
    { tsEpoch: 7, high: 102.3, low: 101.5 },
  ];
  const touches = countZoneTouches(candles, zone, 8);
  assert.equal(touches.touch_count, 2);
  assert.equal(touches.touch_events.length, 2);
});

run("analyzer returns strongest zones + advisory likelihood shape on clean bouncing market", () => {
  const points = buildSeries({
    points: 2200,
    stepSeconds: 300,
    generator: (index) => {
      const wave = Math.sin(index / 6) * 4.7;
      const modulation = Math.sin(index / 27) * 0.9;
      return 100 + wave + modulation;
    },
  });
  const nowEpoch = points[points.length - 1].tsEpoch;
  const result = analyzeWaveZones({
    symbol: "TEST-USD",
    pricePoints: points,
    currentPrice: points[points.length - 1].price,
    nowEpoch,
    wallClockEpoch: nowEpoch,
  });

  assert.equal(result.symbol, "TEST-USD");
  assert.ok(result.summary.strongest_overall_low_zone);
  assert.ok(result.summary.strongest_overall_high_zone);
  assert.ok(result.summary.weighted_low_revisit_likelihood_pct >= 0);
  assert.ok(result.summary.weighted_low_revisit_likelihood_pct <= 100);
  assert.ok(result.summary.weighted_high_revisit_likelihood_pct >= 0);
  assert.ok(result.summary.weighted_high_revisit_likelihood_pct <= 100);
  assert.ok(typeof result.timeframes["24h"].insufficient_data === "boolean");
});

run("analyzer handles insufficient data across all configured windows", () => {
  const points = [
    { tsEpoch: 1_770_000_000, price: 100 },
    { tsEpoch: 1_770_000_120, price: 100.3 },
    { tsEpoch: 1_770_000_240, price: 99.9 },
  ];
  const result = analyzeWaveZones({
    symbol: "THIN-USD",
    pricePoints: points,
    currentPrice: 100,
    nowEpoch: 1_770_000_300,
    wallClockEpoch: 1_770_000_300,
  });

  for (const timeframe of TIMEFRAME_CONFIG) {
    assert.equal(result.timeframes[timeframe.key].insufficient_data, true);
    assert.ok(typeof result.timeframes[timeframe.key].insufficient_reason_code === "string");
    assert.ok(typeof result.timeframes[timeframe.key].insufficient_reason_message === "string");
    assert.ok(Number.isFinite(result.timeframes[timeframe.key].observed_history_span_minutes));
    assert.ok(Number.isFinite(result.timeframes[timeframe.key].observed_candle_count));
  }
});

run("insufficient reason uses stale_snapshot_history when latest snapshots are stale to wall clock", () => {
  const points = buildSeries({
    startEpoch: 1_770_000_000,
    points: 300,
    stepSeconds: 300,
    generator: (index) => 100 + Math.sin(index / 5),
  });
  const latestTs = points[points.length - 1].tsEpoch;
  const result = analyzeWaveZones({
    symbol: "STALE-USD",
    pricePoints: points,
    currentPrice: points[points.length - 1].price,
    nowEpoch: latestTs,
    wallClockEpoch: latestTs + (2 * 3600),
    staleHistoryThresholdSeconds: 10 * 60,
  });

  assert.equal(result.timeframes["1h"].insufficient_data, true);
  assert.equal(result.timeframes["1h"].insufficient_reason_code, "stale_snapshot_history");
});

run("insufficient reason uses insufficient_candle_count when span is present but candle density is thin", () => {
  const startEpoch = 1_770_000_000;
  const points = [
    { tsEpoch: startEpoch + 0, price: 100 },
    { tsEpoch: startEpoch + 600, price: 100.4 },
    { tsEpoch: startEpoch + 1200, price: 99.8 },
    { tsEpoch: startEpoch + 1800, price: 100.1 },
    { tsEpoch: startEpoch + 2400, price: 99.9 },
  ];
  const nowEpoch = points[points.length - 1].tsEpoch;
  const result = analyzeWaveZones({
    symbol: "THIN-1H-USD",
    pricePoints: points,
    currentPrice: points[points.length - 1].price,
    nowEpoch,
    wallClockEpoch: nowEpoch,
  });

  assert.equal(result.timeframes["1h"].insufficient_data, true);
  assert.equal(result.timeframes["1h"].insufficient_reason_code, "insufficient_candle_count");
});

run("insufficient reason uses no_valid_pivots when candles are monotonic and pivots cannot form", () => {
  const points = buildSeries({
    startEpoch: 1_770_000_000,
    points: 220,
    stepSeconds: 30,
    generator: (index) => 100 + (index * 0.01),
  });
  const nowEpoch = points[points.length - 1].tsEpoch;
  const result = analyzeWaveZones({
    symbol: "MONO-USD",
    pricePoints: points,
    currentPrice: points[points.length - 1].price,
    nowEpoch,
    wallClockEpoch: nowEpoch,
  });

  assert.equal(result.timeframes["1h"].insufficient_data, true);
  assert.equal(result.timeframes["1h"].insufficient_reason_code, "no_valid_pivots");
});

run("insufficient reason uses insufficient_history_span for long windows with short observed span", () => {
  const points = buildSeries({
    startEpoch: 1_770_000_000,
    points: 80,
    stepSeconds: 8,
    generator: (index) => 100 + (Math.sin(index / 4) * 0.2),
  });
  const nowEpoch = points[points.length - 1].tsEpoch;
  const result = analyzeWaveZones({
    symbol: "SHORT-SPAN-USD",
    pricePoints: points,
    currentPrice: points[points.length - 1].price,
    nowEpoch,
    wallClockEpoch: nowEpoch,
  });

  assert.equal(result.timeframes["4h"].insufficient_data, true);
  assert.equal(result.timeframes["4h"].insufficient_reason_code, "insufficient_history_span");
});

run("advisory likelihoods remain in stable ranges for slow bleed and noisy sideways fixtures", () => {
  const slowBleed = buildSeries({
    points: 1300,
    stepSeconds: 600,
    generator: (index) => 120 - (index * 0.015) + (Math.sin(index / 9) * 0.8),
  });

  let seed = 42;
  const rand = () => {
    seed = (seed * 1664525 + 1013904223) % 4294967296;
    return seed / 4294967296;
  };
  const noisySideways = buildSeries({
    points: 1300,
    stepSeconds: 600,
    generator: () => 75 + ((rand() - 0.5) * 2.2),
  });

  for (const fixture of [slowBleed, noisySideways]) {
    const nowEpoch = fixture[fixture.length - 1].tsEpoch;
    const result = analyzeWaveZones({
      symbol: "FIXTURE-USD",
      pricePoints: fixture,
      currentPrice: fixture[fixture.length - 1].price,
      nowEpoch,
      wallClockEpoch: nowEpoch,
    });

    assert.ok(result.summary.weighted_low_revisit_likelihood_pct >= 0);
    assert.ok(result.summary.weighted_low_revisit_likelihood_pct <= 100);
    assert.ok(result.summary.weighted_high_revisit_likelihood_pct >= 0);
    assert.ok(result.summary.weighted_high_revisit_likelihood_pct <= 100);
  }
});

run("snapshot aggregation builds bounded candle series for analysis", () => {
  const points = buildSeries({
    points: 24,
    stepSeconds: 60,
    generator: (index) => 100 + (index * 0.1),
  });
  const candles = buildCandlesFromSnapshots(points, 300);
  assert.ok(candles.length >= 4);
  assert.ok(candles[0].open > 0);
  assert.ok(candles[0].high >= candles[0].low);
});
