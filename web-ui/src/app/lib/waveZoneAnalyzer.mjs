const TIMEFRAME_CONFIG = [
  { key: "1h", windowSeconds: 60 * 60, pivotWidth: 2, weight: 0.08 },
  { key: "4h", windowSeconds: 4 * 60 * 60, pivotWidth: 3, weight: 0.15 },
  { key: "8h", windowSeconds: 8 * 60 * 60, pivotWidth: 3, weight: 0.17 },
  { key: "16h", windowSeconds: 16 * 60 * 60, pivotWidth: 3, weight: 0.18 },
  { key: "24h", windowSeconds: 24 * 60 * 60, pivotWidth: 3, weight: 0.2 },
  { key: "3d", windowSeconds: 3 * 24 * 60 * 60, pivotWidth: 4, weight: 0.12 },
  { key: "7d", windowSeconds: 7 * 24 * 60 * 60, pivotWidth: 5, weight: 0.1 },
];

const DEFAULT_STALE_SNAPSHOT_THRESHOLD_SECONDS = 20 * 60;
const MIN_HISTORY_SPAN_RATIO_BY_WINDOW = 0.25;
const MIN_HISTORY_SPAN_FLOOR_MINUTES = 12;

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function mean(values) {
  if (!Array.isArray(values) || values.length === 0) {
    return 0;
  }
  return values.reduce((acc, value) => acc + value, 0) / values.length;
}

function normalizePricePoints(points) {
  if (!Array.isArray(points)) {
    return [];
  }
  return points
    .map((row) => ({
      tsEpoch: Number(row?.tsEpoch ?? 0),
      price: Number(row?.price ?? 0),
    }))
    .filter((row) => Number.isFinite(row.tsEpoch) && Number.isFinite(row.price) && row.tsEpoch > 0 && row.price > 0)
    .sort((left, right) => left.tsEpoch - right.tsEpoch);
}

function buildCandlesFromSnapshots(points, bucketSeconds) {
  const rows = normalizePricePoints(points);
  if (rows.length === 0) {
    return [];
  }

  const bucket = Math.max(1, Math.trunc(bucketSeconds));
  const map = new Map();
  for (const point of rows) {
    const key = Math.floor(point.tsEpoch / bucket) * bucket;
    const existing = map.get(key);
    if (!existing) {
      map.set(key, {
        tsEpoch: key,
        open: point.price,
        high: point.price,
        low: point.price,
        close: point.price,
      });
      continue;
    }
    existing.high = Math.max(existing.high, point.price);
    existing.low = Math.min(existing.low, point.price);
    existing.close = point.price;
  }

  return Array.from(map.values()).sort((left, right) => left.tsEpoch - right.tsEpoch);
}

function detectSwingPivots(candles, width) {
  const rows = Array.isArray(candles) ? candles : [];
  const n = Math.max(1, Math.trunc(width));
  const highs = [];
  const lows = [];
  for (let index = n; index < rows.length - n; index += 1) {
    const row = rows[index];
    let isHigh = true;
    let isLow = true;
    for (let offset = 1; offset <= n; offset += 1) {
      const left = rows[index - offset];
      const right = rows[index + offset];
      if (!left || !right) {
        isHigh = false;
        isLow = false;
        break;
      }
      if (!(row.high > left.high && row.high > right.high)) {
        isHigh = false;
      }
      if (!(row.low < left.low && row.low < right.low)) {
        isLow = false;
      }
      if (!isHigh && !isLow) {
        break;
      }
    }
    if (isHigh) {
      highs.push({ tsEpoch: row.tsEpoch, price: row.high, index, type: "high" });
    }
    if (isLow) {
      lows.push({ tsEpoch: row.tsEpoch, price: row.low, index, type: "low" });
    }
  }
  return { highs, lows };
}

function clusterPivotZones(pivots, toleranceAbs) {
  const rows = Array.isArray(pivots) ? [...pivots] : [];
  if (rows.length === 0) {
    return [];
  }
  const tol = Math.max(Number(toleranceAbs) || 0, 1e-8);
  rows.sort((left, right) => left.price - right.price);

  const clusters = [];
  for (const pivot of rows) {
    const last = clusters[clusters.length - 1];
    if (!last) {
      clusters.push({ pivots: [pivot] });
      continue;
    }
    const center = mean(last.pivots.map((row) => row.price));
    if (Math.abs(pivot.price - center) <= tol) {
      last.pivots.push(pivot);
    } else {
      clusters.push({ pivots: [pivot] });
    }
  }

  return clusters.map((cluster) => {
    const prices = cluster.pivots.map((row) => row.price);
    const zoneCenter = mean(prices);
    const rawMin = Math.min(...prices);
    const rawMax = Math.max(...prices);
    const halfPad = tol / 2;
    return {
      zone_min: rawMin - halfPad,
      zone_max: rawMax + halfPad,
      zone_center: zoneCenter,
      pivot_count: cluster.pivots.length,
      pivots: cluster.pivots,
      touch_count: 0,
      touch_events: [],
      last_touch_ts: null,
      last_touch_age_hours: null,
      reaction_strength: 0,
      reaction_avg_move_pct: 0,
      reaction_best_move_pct: 0,
      reaction_success_count: 0,
      score: 0,
      score_components: null,
      proximity_pct: 0,
    };
  });
}

function candleTouchesZone(candle, zone) {
  return candle.low <= zone.zone_max && candle.high >= zone.zone_min;
}

function countZoneTouches(candles, zone, nowEpoch) {
  const rows = Array.isArray(candles) ? candles : [];
  let inZone = false;
  let entryIndex = -1;
  let lastInsideIndex = -1;
  const events = [];

  for (let index = 0; index < rows.length; index += 1) {
    const candle = rows[index];
    const touched = candleTouchesZone(candle, zone);
    if (touched) {
      if (!inZone) {
        inZone = true;
        entryIndex = index;
      }
      lastInsideIndex = index;
    } else if (inZone) {
      events.push({
        entryIndex,
        exitIndex: lastInsideIndex,
        entryTs: rows[entryIndex].tsEpoch,
        exitTs: rows[lastInsideIndex].tsEpoch,
      });
      inZone = false;
      entryIndex = -1;
      lastInsideIndex = -1;
    }
  }

  if (inZone && entryIndex >= 0 && lastInsideIndex >= 0) {
    events.push({
      entryIndex,
      exitIndex: lastInsideIndex,
      entryTs: rows[entryIndex].tsEpoch,
      exitTs: rows[lastInsideIndex].tsEpoch,
    });
  }

  const lastTouchTs = events.length > 0 ? events[events.length - 1].exitTs : null;
  const lastTouchAgeHours = lastTouchTs
    ? Math.max((nowEpoch - lastTouchTs) / 3600, 0)
    : null;

  return {
    touch_count: events.length,
    touch_events: events,
    last_touch_ts: lastTouchTs,
    last_touch_age_hours: lastTouchAgeHours,
  };
}

function measureZoneReactions(candles, zone, side, lookaheadCandles, zoneWidthPct) {
  const rows = Array.isArray(candles) ? candles : [];
  const horizon = Math.max(1, Math.trunc(lookaheadCandles));
  const moves = [];
  let successes = 0;
  const successThresholdPct = Math.max(zoneWidthPct * 0.8, 0.2);

  for (const event of zone.touch_events) {
    const start = event.exitIndex + 1;
    if (start >= rows.length) {
      continue;
    }
    const end = Math.min(rows.length - 1, start + horizon - 1);
    const lookahead = rows.slice(start, end + 1);
    if (lookahead.length === 0) {
      continue;
    }
    if (side === "low") {
      const maxHigh = Math.max(...lookahead.map((row) => row.high));
      const move = ((maxHigh - zone.zone_center) / zone.zone_center) * 100;
      moves.push(move);
      if (move >= successThresholdPct) {
        successes += 1;
      }
    } else {
      const minLow = Math.min(...lookahead.map((row) => row.low));
      const move = ((zone.zone_center - minLow) / zone.zone_center) * 100;
      moves.push(move);
      if (move >= successThresholdPct) {
        successes += 1;
      }
    }
  }

  const avg = moves.length > 0 ? mean(moves) : 0;
  const best = moves.length > 0 ? Math.max(...moves) : 0;
  return {
    reaction_strength: Math.max(avg, 0),
    reaction_avg_move_pct: Math.max(avg, 0),
    reaction_best_move_pct: Math.max(best, 0),
    reaction_success_count: successes,
  };
}

function scoreZones(zones, currentPrice, timeframeHours, side) {
  const rows = Array.isArray(zones) ? zones : [];
  if (rows.length === 0) {
    return rows;
  }

  const maxTouches = Math.max(1, ...rows.map((zone) => zone.touch_count));
  const maxReaction = Math.max(1e-6, ...rows.map((zone) => zone.reaction_strength));
  const proximityDenom = Math.max(currentPrice * 0.08, 1e-6);

  for (const zone of rows) {
    const touchNorm = clamp(zone.touch_count / maxTouches, 0, 1);
    const recencyNorm = zone.last_touch_age_hours === null
      ? 0
      : clamp(1 - (zone.last_touch_age_hours / Math.max(timeframeHours, 1)), 0, 1);
    const reactionNorm = clamp(zone.reaction_strength / maxReaction, 0, 1);
    const proximityNorm = clamp(1 - (Math.abs(currentPrice - zone.zone_center) / proximityDenom), 0, 1);
    zone.proximity_pct = proximityNorm * 100;

    const score = (
      (0.35 * touchNorm)
      + (0.25 * recencyNorm)
      + (0.25 * reactionNorm)
      + (0.15 * proximityNorm)
    ) * 100;

    zone.score = clamp(score, 0, 100);
    zone.score_components = {
      normalized_touch_count: Number((touchNorm * 100).toFixed(3)),
      normalized_recency: Number((recencyNorm * 100).toFixed(3)),
      normalized_reaction_strength: Number((reactionNorm * 100).toFixed(3)),
      normalized_proximity_to_current_price: Number((proximityNorm * 100).toFixed(3)),
      side,
    };
  }

  return rows;
}

function selectStrongestZone(zones) {
  if (!Array.isArray(zones) || zones.length === 0) {
    return null;
  }
  return [...zones].sort(
    (left, right) => (right.score - left.score) || (right.touch_count - left.touch_count),
  )[0];
}

function selectMostTouchedZone(zones) {
  if (!Array.isArray(zones) || zones.length === 0) {
    return null;
  }
  return [...zones].sort(
    (left, right) => (right.touch_count - left.touch_count) || (right.score - left.score),
  )[0];
}

function formatZone(zone) {
  if (!zone) {
    return null;
  }
  return {
    center: Number(zone.zone_center.toFixed(8)),
    min: Number(zone.zone_min.toFixed(8)),
    max: Number(zone.zone_max.toFixed(8)),
    touch_count: zone.touch_count,
    last_touch_age_hours: zone.last_touch_age_hours === null
      ? null
      : Number(zone.last_touch_age_hours.toFixed(3)),
    reaction_strength: Number(zone.reaction_strength.toFixed(6)),
    score: Number(zone.score.toFixed(6)),
    pivot_count: zone.pivot_count,
    proximity_pct: Number(zone.proximity_pct.toFixed(6)),
  };
}

function deriveLikelihoods(lowZone, highZone) {
  if (!lowZone && !highZone) {
    return { low: 0, high: 0 };
  }
  if (lowZone && !highZone) {
    const low = clamp(55 + (0.4 * lowZone.score), 35, 95);
    return { low, high: clamp(100 - low, 5, 55) };
  }
  if (!lowZone && highZone) {
    const high = clamp(55 + (0.4 * highZone.score), 35, 95);
    return { low: clamp(100 - high, 5, 55), high };
  }

  const lowRaw = (0.7 * lowZone.score) + (0.3 * lowZone.proximity_pct);
  const highRaw = (0.7 * highZone.score) + (0.3 * highZone.proximity_pct);
  const low = clamp(50 + ((lowRaw - highRaw) * 0.35), 5, 95);
  const high = clamp(50 + ((highRaw - lowRaw) * 0.35), 5, 95);
  return { low, high };
}

function buildInsufficientResult({
  reasonCode,
  reasonMessage,
  sampleCount,
  candleCount,
  spanMinutes,
}) {
  return {
    strongest_low_zone: null,
    most_touched_low_zone: null,
    strongest_high_zone: null,
    most_touched_high_zone: null,
    low_revisit_likelihood_pct: 0,
    high_revisit_likelihood_pct: 0,
    insufficient_data: true,
    insufficient_reason_code: reasonCode,
    insufficient_reason_message: reasonMessage,
    observed_history_span_minutes: Number(spanMinutes.toFixed(3)),
    observed_candle_count: candleCount,
    sample_count: sampleCount,
    candle_count: candleCount,
    data_note: "Insufficient data",
  };
}

function analyzeSingleTimeframe(points, currentPrice, nowEpoch, timeframe, options = {}) {
  const rows = normalizePricePoints(points).filter(
    (row) => row.tsEpoch >= nowEpoch - timeframe.windowSeconds && row.tsEpoch <= nowEpoch,
  );
  const bucketSeconds = Math.max(60, Math.round(timeframe.windowSeconds / 120));
  const candles = buildCandlesFromSnapshots(rows, bucketSeconds);
  const timeframeHours = timeframe.windowSeconds / 3600;
  const observedHistorySpanMinutes = rows.length >= 2
    ? Math.max((rows[rows.length - 1].tsEpoch - rows[0].tsEpoch) / 60, 0)
    : 0;
  const observedCandleCount = candles.length;
  const latestSnapshotTs = rows.length > 0
    ? rows[rows.length - 1].tsEpoch
    : (points[points.length - 1]?.tsEpoch ?? null);
  const wallClockEpoch = Number.isFinite(options.wallClockEpoch) && options.wallClockEpoch > 0
    ? options.wallClockEpoch
    : nowEpoch;
  const staleThresholdSeconds = Number.isFinite(options.staleHistoryThresholdSeconds)
    && options.staleHistoryThresholdSeconds > 0
    ? options.staleHistoryThresholdSeconds
    : DEFAULT_STALE_SNAPSHOT_THRESHOLD_SECONDS;
  const snapshotAgeSeconds = latestSnapshotTs === null
    ? null
    : Math.max(wallClockEpoch - latestSnapshotTs, 0);
  const minHistorySpanMinutes = Math.max(
    (timeframe.windowSeconds / 60) * MIN_HISTORY_SPAN_RATIO_BY_WINDOW,
    MIN_HISTORY_SPAN_FLOOR_MINUTES,
  );

  if (snapshotAgeSeconds !== null && snapshotAgeSeconds > staleThresholdSeconds) {
    return buildInsufficientResult({
      reasonCode: "stale_snapshot_history",
      reasonMessage: (
        `Latest snapshot is ${(snapshotAgeSeconds / 60).toFixed(1)}m old `
        + `(threshold ${(staleThresholdSeconds / 60).toFixed(1)}m).`
      ),
      sampleCount: rows.length,
      candleCount: observedCandleCount,
      spanMinutes: observedHistorySpanMinutes,
    });
  }

  if (observedHistorySpanMinutes < minHistorySpanMinutes) {
    return buildInsufficientResult({
      reasonCode: "insufficient_history_span",
      reasonMessage: (
        `Observed span ${observedHistorySpanMinutes.toFixed(1)}m is below `
        + `${minHistorySpanMinutes.toFixed(1)}m required for ${timeframe.key}.`
      ),
      sampleCount: rows.length,
      candleCount: observedCandleCount,
      spanMinutes: observedHistorySpanMinutes,
    });
  }

  const minCandlesRequired = Math.max(18, (timeframe.pivotWidth * 2) + 8);

  if (candles.length < minCandlesRequired || currentPrice <= 0) {
    return buildInsufficientResult({
      reasonCode: "insufficient_candle_count",
      reasonMessage: (
        `Observed ${candles.length} candles, required at least ${minCandlesRequired}.`
      ),
      sampleCount: rows.length,
      candleCount: observedCandleCount,
      spanMinutes: observedHistorySpanMinutes,
    });
  }

  const pivots = detectSwingPivots(candles, timeframe.pivotWidth);
  if (pivots.highs.length === 0 && pivots.lows.length === 0) {
    return buildInsufficientResult({
      reasonCode: "no_valid_pivots",
      reasonMessage: "No valid swing highs/lows detected for this window.",
      sampleCount: rows.length,
      candleCount: observedCandleCount,
      spanMinutes: observedHistorySpanMinutes,
    });
  }

  const avgRange = mean(candles.map((row) => row.high - row.low));
  const zoneWidthAbs = Math.max(currentPrice * 0.005, 0.25 * avgRange);
  const zoneWidthPct = (zoneWidthAbs / currentPrice) * 100;
  const lookaheadCandles = Math.max(3, Math.round(candles.length / 12));

  const lowZones = clusterPivotZones(pivots.lows, zoneWidthAbs);
  const highZones = clusterPivotZones(pivots.highs, zoneWidthAbs);

  for (const zone of lowZones) {
    Object.assign(zone, countZoneTouches(candles, zone, nowEpoch));
    Object.assign(zone, measureZoneReactions(candles, zone, "low", lookaheadCandles, zoneWidthPct));
  }
  for (const zone of highZones) {
    Object.assign(zone, countZoneTouches(candles, zone, nowEpoch));
    Object.assign(zone, measureZoneReactions(candles, zone, "high", lookaheadCandles, zoneWidthPct));
  }

  scoreZones(lowZones, currentPrice, timeframeHours, "low");
  scoreZones(highZones, currentPrice, timeframeHours, "high");

  const strongestLow = selectStrongestZone(lowZones);
  const strongestHigh = selectStrongestZone(highZones);
  const mostTouchedLow = selectMostTouchedZone(lowZones);
  const mostTouchedHigh = selectMostTouchedZone(highZones);

  const likelihood = deriveLikelihoods(strongestLow, strongestHigh);
  if (strongestLow === null && strongestHigh === null) {
    return buildInsufficientResult({
      reasonCode: "no_valid_pivots",
      reasonMessage: "No meaningful support/resistance zones were produced.",
      sampleCount: rows.length,
      candleCount: observedCandleCount,
      spanMinutes: observedHistorySpanMinutes,
    });
  }

  return {
    strongest_low_zone: formatZone(strongestLow),
    most_touched_low_zone: formatZone(mostTouchedLow),
    strongest_high_zone: formatZone(strongestHigh),
    most_touched_high_zone: formatZone(mostTouchedHigh),
    low_revisit_likelihood_pct: Number(likelihood.low.toFixed(3)),
    high_revisit_likelihood_pct: Number(likelihood.high.toFixed(3)),
    insufficient_data: false,
    insufficient_reason_code: null,
    insufficient_reason_message: null,
    observed_history_span_minutes: Number(observedHistorySpanMinutes.toFixed(3)),
    observed_candle_count: observedCandleCount,
    sample_count: rows.length,
    candle_count: candles.length,
    zone_width_pct: Number(zoneWidthPct.toFixed(6)),
    lookahead_candles: lookaheadCandles,
  };
}

function dominantBias(low, high) {
  const delta = low - high;
  if (delta > 6) {
    return "LOW_REVISIT_MORE_LIKELY";
  }
  if (delta < -6) {
    return "HIGH_REVISIT_MORE_LIKELY";
  }
  return "BALANCED";
}

function selectStrongestOverall(timeframes, side) {
  const winner = [];
  for (const timeframe of TIMEFRAME_CONFIG) {
    const row = timeframes[timeframe.key];
    if (!row || row.insufficient_data) {
      continue;
    }
    const zone = side === "low" ? row.strongest_low_zone : row.strongest_high_zone;
    if (!zone) {
      continue;
    }
    winner.push({
      zone,
      weightedScore: zone.score * timeframe.weight,
    });
  }
  if (winner.length === 0) {
    return null;
  }
  winner.sort((left, right) => right.weightedScore - left.weightedScore);
  return winner[0].zone;
}

function analyzeWaveZones({
  symbol,
  pricePoints,
  currentPrice,
  nowEpoch,
  wallClockEpoch,
  staleHistoryThresholdSeconds,
}) {
  const rows = normalizePricePoints(pricePoints);
  const latestPrice = Number.isFinite(currentPrice) && currentPrice > 0
    ? currentPrice
    : (rows[rows.length - 1]?.price ?? 0);
  const anchorNow = Number.isFinite(nowEpoch) && nowEpoch > 0
    ? nowEpoch
    : (rows[rows.length - 1]?.tsEpoch ?? (Date.now() / 1000));
  const wallClockNow = Number.isFinite(wallClockEpoch) && wallClockEpoch > 0
    ? wallClockEpoch
    : (Date.now() / 1000);
  const latestSnapshotTs = rows[rows.length - 1]?.tsEpoch ?? null;
  const latestSnapshotAgeMinutes = latestSnapshotTs === null
    ? null
    : Math.max((wallClockNow - latestSnapshotTs) / 60, 0);

  const timeframeOutput = {};
  for (const timeframe of TIMEFRAME_CONFIG) {
    timeframeOutput[timeframe.key] = analyzeSingleTimeframe(
      rows,
      latestPrice,
      anchorNow,
      timeframe,
      {
        wallClockEpoch: wallClockNow,
        staleHistoryThresholdSeconds,
      },
    );
  }

  let weightedLowSum = 0;
  let weightedHighSum = 0;
  let usedWeight = 0;
  for (const timeframe of TIMEFRAME_CONFIG) {
    const row = timeframeOutput[timeframe.key];
    if (!row || row.insufficient_data) {
      continue;
    }
    weightedLowSum += timeframe.weight * row.low_revisit_likelihood_pct;
    weightedHighSum += timeframe.weight * row.high_revisit_likelihood_pct;
    usedWeight += timeframe.weight;
  }

  const weightedLow = usedWeight > 0 ? weightedLowSum / usedWeight : 0;
  const weightedHigh = usedWeight > 0 ? weightedHighSum / usedWeight : 0;
  const strongestOverallLow = selectStrongestOverall(timeframeOutput, "low");
  const strongestOverallHigh = selectStrongestOverall(timeframeOutput, "high");

  return {
    symbol,
    current_price: Number(latestPrice.toFixed(8)),
    summary: {
      weighted_low_revisit_likelihood_pct: Number(weightedLow.toFixed(3)),
      weighted_high_revisit_likelihood_pct: Number(weightedHigh.toFixed(3)),
      dominant_bias: dominantBias(weightedLow, weightedHigh),
      strongest_overall_low_zone: strongestOverallLow
        ? {
            center: strongestOverallLow.center,
            min: strongestOverallLow.min,
            max: strongestOverallLow.max,
          }
        : null,
      strongest_overall_high_zone: strongestOverallHigh
        ? {
            center: strongestOverallHigh.center,
            min: strongestOverallHigh.min,
            max: strongestOverallHigh.max,
          }
        : null,
      analysis_anchor_at: new Date(anchorNow * 1000).toISOString(),
      latest_snapshot_at: latestSnapshotTs === null
        ? null
        : new Date(latestSnapshotTs * 1000).toISOString(),
      latest_snapshot_age_minutes: latestSnapshotAgeMinutes === null
        ? null
        : Number(latestSnapshotAgeMinutes.toFixed(3)),
      history_point_count: rows.length,
      data_quality_note: (
        "Derived from observed snapshot history available to the UI. Advisory-only likelihood estimates, not execution logic or guarantees."
      ),
    },
    timeframes: timeframeOutput,
  };
}

export {
  TIMEFRAME_CONFIG,
  buildCandlesFromSnapshots,
  detectSwingPivots,
  clusterPivotZones,
  countZoneTouches,
  analyzeWaveZones,
};
