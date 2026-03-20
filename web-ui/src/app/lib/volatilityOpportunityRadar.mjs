const RADAR_WINDOWS = [
  { key: "30m", seconds: 30 * 60, weight: 0.3 },
  { key: "1h", seconds: 60 * 60, weight: 0.35 },
  { key: "4h", seconds: 4 * 60 * 60, weight: 0.25 },
  { key: "8h", seconds: 8 * 60 * 60, weight: 0.1 },
];

const STALE_SNAPSHOT_THRESHOLD_SECONDS = 20 * 60;

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function average(values) {
  if (!Array.isArray(values) || values.length === 0) {
    return null;
  }
  return values.reduce((acc, value) => acc + value, 0) / values.length;
}

function stddev(values) {
  if (!Array.isArray(values) || values.length < 2) {
    return 0;
  }
  const mean = average(values) ?? 0;
  const variance = values.reduce((acc, value) => acc + ((value - mean) ** 2), 0) / values.length;
  return Math.sqrt(Math.max(variance, 0));
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
    .filter(
      (row) => Number.isFinite(row.tsEpoch)
        && row.tsEpoch > 0
        && Number.isFinite(row.price)
        && row.price > 0,
    )
    .sort((left, right) => left.tsEpoch - right.tsEpoch);
}

function pickRowsWithinWindow(rows, nowEpoch, windowSeconds) {
  return rows.filter(
    (row) => row.tsEpoch >= nowEpoch - windowSeconds && row.tsEpoch <= nowEpoch,
  );
}

function returnsPct(rows) {
  const output = [];
  for (let index = 1; index < rows.length; index += 1) {
    const prev = rows[index - 1].price;
    const curr = rows[index].price;
    if (prev <= 0) {
      continue;
    }
    output.push(((curr - prev) / prev) * 100);
  }
  return output;
}

function mapOpportunityLabel(score) {
  if (score === null || !Number.isFinite(score)) {
    return null;
  }
  if (score >= 70) {
    return "HIGH";
  }
  if (score >= 40) {
    return "MEDIUM";
  }
  return "LOW";
}

function buildInsufficient({
  reasonCode,
  reasonMessage,
  observedHistorySpanMinutes,
  observedPointCount,
}) {
  const dataQuality = {
    status: reasonCode === "stale_snapshot_history" ? "STALE" : "INSUFFICIENT",
    reason: reasonCode,
    sample_counts: {
      observed_points: observedPointCount,
      required_points: 10,
    },
    last_update_ts: null,
  };
  return {
    score: null,
    label: null,
    reason: reasonMessage,
    confidence_label: "LOW",
    stretch_score: null,
    volatility_spike_score: null,
    bounce_context_score: null,
    liquidity_quality_score: null,
    observed_history_span_minutes: Number(observedHistorySpanMinutes.toFixed(3)),
    observed_point_count: observedPointCount,
    insufficient_data: true,
    insufficient_reason_code: reasonCode,
    insufficient_reason_message: reasonMessage,
    window_coverage: {
      total_windows: RADAR_WINDOWS.length,
      windows_with_metrics: 0,
      keys_with_metrics: [],
    },
    volatility_state: "LOW",
    volatility_score: null,
    components: {
      stretch_score: null,
      volatility_spike_score: null,
      bounce_context_score: null,
      liquidity_quality_score: null,
    },
    confidence_score: 0,
    data_quality: dataQuality,
  };
}

function mapVolatilityState(score) {
  if (!Number.isFinite(score)) {
    return "LOW";
  }
  if (score >= 80) {
    return "EXTREME";
  }
  if (score >= 60) {
    return "EXPANDING";
  }
  if (score >= 35) {
    return "NORMAL";
  }
  return "LOW";
}

function computeStretchScore(rows, currentPrice) {
  if (rows.length < 4 || currentPrice <= 0) {
    return null;
  }
  const prices = rows.map((row) => row.price);
  const meanPrice = average(prices);
  if (meanPrice === null || meanPrice <= 0) {
    return null;
  }
  const minPrice = Math.min(...prices);
  const maxPrice = Math.max(...prices);
  const midpoint = (minPrice + maxPrice) / 2;
  const belowMeanPct = Math.max(((meanPrice - currentPrice) / meanPrice) * 100, 0);
  const belowMidPct = midpoint > 0 ? Math.max(((midpoint - currentPrice) / midpoint) * 100, 0) : 0;

  const meanNorm = clamp(belowMeanPct / 4.5, 0, 1);
  const midNorm = clamp(belowMidPct / 4.5, 0, 1);
  return clamp(((0.65 * meanNorm) + (0.35 * midNorm)) * 100, 0, 100);
}

function computeVolatilitySpikeScore(rows, baselineRows) {
  if (rows.length < 6 || baselineRows.length < 10) {
    return null;
  }
  const recentReturns = returnsPct(rows);
  const baselineReturns = returnsPct(baselineRows);
  if (recentReturns.length < 4 || baselineReturns.length < 6) {
    return null;
  }

  const recentTailSize = Math.max(4, Math.floor(recentReturns.length * 0.35));
  const recentTail = recentReturns.slice(-recentTailSize);
  const recentVol = stddev(recentTail);
  const baseVol = Math.max(stddev(baselineReturns), 1e-6);
  const volRatio = recentVol / baseVol;
  const ratioNorm = clamp((volRatio - 1) / 2.2, 0, 1);

  const recentPrices = rows.map((row) => row.price);
  const basePrices = baselineRows.map((row) => row.price);
  const recentMean = average(recentPrices) ?? 0;
  const baseMean = average(basePrices) ?? 0;
  const recentRangePct = recentMean > 0
    ? ((Math.max(...recentPrices) - Math.min(...recentPrices)) / recentMean) * 100
    : 0;
  const baseRangePct = baseMean > 0
    ? ((Math.max(...basePrices) - Math.min(...basePrices)) / baseMean) * 100
    : 0;
  const rangeRatio = baseRangePct > 0 ? recentRangePct / baseRangePct : 0;
  const rangeNorm = clamp((rangeRatio - 1) / 2, 0, 1);

  return clamp(((0.6 * ratioNorm) + (0.4 * rangeNorm)) * 100, 0, 100);
}

function computeBounceContextScore(rows, currentPrice, volatilitySpikeScore) {
  if (rows.length < 6 || currentPrice <= 0) {
    return null;
  }
  const prices = rows.map((row) => row.price);
  const low = Math.min(...prices);
  const high = Math.max(...prices);
  const range = Math.max(high - low, 1e-9);
  const rangePos = (currentPrice - low) / range;
  const nearLowNorm = clamp(1 - rangePos, 0, 1);
  const flushNorm = clamp(((high - currentPrice) / Math.max(high, 1e-9)) * 100 / 6, 0, 1);

  const lookbackSize = Math.max(4, Math.floor(rows.length * 0.3));
  const lookbackPrice = rows[Math.max(0, rows.length - lookbackSize)].price;
  const shortMomentumPct = lookbackPrice > 0
    ? ((currentPrice - lookbackPrice) / lookbackPrice) * 100
    : 0;
  const momentumNorm = clamp((shortMomentumPct + 1.5) / 4.0, 0, 1);
  const bleedPenalty = clamp(Math.abs(Math.min(shortMomentumPct, 0)) / 3.0, 0, 1);
  const volAssist = volatilitySpikeScore === null
    ? 0.4
    : clamp(volatilitySpikeScore / 100, 0, 1);

  const raw = (
    (0.35 * nearLowNorm)
    + (0.30 * flushNorm)
    + (0.25 * momentumNorm)
    + (0.10 * volAssist)
    - (0.25 * bleedPenalty)
  );
  return clamp(raw * 100, 0, 100);
}

function computeLiquidityQualityScore(latestSnapshot) {
  if (!latestSnapshot || typeof latestSnapshot !== "object") {
    return null;
  }
  const spreadBps = Number(latestSnapshot.spreadBps);
  const quality = String(latestSnapshot.quality ?? "").toLowerCase();
  const hasSpread = Number.isFinite(spreadBps) && spreadBps >= 0;

  if (!hasSpread && !quality) {
    return null;
  }

  let score = 65;
  if (hasSpread) {
    if (spreadBps <= 5) {
      score = 100;
    } else if (spreadBps <= 15) {
      score = 90;
    } else if (spreadBps <= 30) {
      score = 75;
    } else if (spreadBps <= 60) {
      score = 60;
    } else if (spreadBps <= 120) {
      score = 40;
    } else if (spreadBps <= 250) {
      score = 25;
    } else {
      score = 10;
    }
  }

  if (quality && quality !== "ok") {
    if (quality.includes("spread_too_wide")) {
      score -= 25;
    } else if (quality.includes("order_book_tape_mismatch")) {
      score -= 20;
    } else if (quality.includes("warming_up_history")) {
      score -= 15;
    } else {
      score -= 10;
    }
  }

  return clamp(score, 0, 100);
}

function weightedComponentAverage(windowScores, key) {
  let weightedSum = 0;
  let weightTotal = 0;
  for (const row of windowScores) {
    const value = row[key];
    if (value === null || !Number.isFinite(value)) {
      continue;
    }
    weightedSum += row.weight * value;
    weightTotal += row.weight;
  }
  if (weightTotal <= 0) {
    return null;
  }
  return weightedSum / weightTotal;
}

function confidenceLabel({
  observedPointCount,
  observedHistorySpanMinutes,
  windowsWithMetrics,
}) {
  if (windowsWithMetrics >= 3 && observedPointCount >= 80 && observedHistorySpanMinutes >= 240) {
    return "HIGH";
  }
  if (windowsWithMetrics >= 2 && observedPointCount >= 30 && observedHistorySpanMinutes >= 90) {
    return "MEDIUM";
  }
  return "LOW";
}

function buildReason({
  stretchScore,
  volatilitySpikeScore,
  bounceContextScore,
  liquidityQualityScore,
}) {
  const parts = [];
  if ((stretchScore ?? 0) >= 70) {
    parts.push("Deep stretch below short-term mean");
  } else if ((stretchScore ?? 0) >= 45) {
    parts.push("Moderate stretch below short-term mean");
  } else {
    parts.push("Mild stretch profile");
  }

  if ((volatilitySpikeScore ?? 0) >= 70) {
    parts.push("with elevated short-term volatility");
  } else if ((volatilitySpikeScore ?? 0) >= 40) {
    parts.push("with moderate volatility expansion");
  } else {
    parts.push("with limited volatility expansion");
  }

  if ((bounceContextScore ?? 0) >= 65) {
    parts.push("and improving bounce context near local lows");
  } else if ((bounceContextScore ?? 0) < 35) {
    parts.push("but weak bounce context (slow-bleed risk)");
  }

  if (liquidityQualityScore !== null && liquidityQualityScore < 35) {
    parts.push("Liquidity/spread quality is weak, so caution is advised.");
  }

  return parts.join(" ").trim();
}

function analyzeVolatilityOpportunity({
  symbol,
  pricePoints,
  latestSnapshot,
  nowEpoch,
  wallClockEpoch,
  staleSnapshotThresholdSeconds = STALE_SNAPSHOT_THRESHOLD_SECONDS,
}) {
  const rows = normalizePricePoints(pricePoints);
  const pointCount = rows.length;
  const latest = rows[rows.length - 1] ?? null;
  const earliest = rows[0] ?? null;
  const anchorNow = Number.isFinite(nowEpoch) && nowEpoch > 0
    ? nowEpoch
    : (latest?.tsEpoch ?? (Date.now() / 1000));
  const wallClockNow = Number.isFinite(wallClockEpoch) && wallClockEpoch > 0
    ? wallClockEpoch
    : (Date.now() / 1000);
  const observedHistorySpanMinutes = (
    pointCount >= 2
      ? Math.max((latest.tsEpoch - earliest.tsEpoch) / 60, 0)
      : 0
  );
  const latestSnapshotAgeMinutes = latest
    ? Math.max((wallClockNow - latest.tsEpoch) / 60, 0)
    : null;

  if (pointCount < 10) {
    return {
      symbol,
      ...buildInsufficient({
        reasonCode: "insufficient_point_count",
        reasonMessage: `Observed ${pointCount} points, need at least 10 for radar.`,
        observedHistorySpanMinutes,
        observedPointCount: pointCount,
      }),
    };
  }

  if (observedHistorySpanMinutes < 20) {
    return {
      symbol,
      ...buildInsufficient({
        reasonCode: "insufficient_history_span",
        reasonMessage: `Observed span ${observedHistorySpanMinutes.toFixed(1)}m is below 20m minimum.`,
        observedHistorySpanMinutes,
        observedPointCount: pointCount,
      }),
    };
  }

  if (
    latestSnapshotAgeMinutes !== null
    && latestSnapshotAgeMinutes > (staleSnapshotThresholdSeconds / 60)
  ) {
    return {
      symbol,
      ...buildInsufficient({
        reasonCode: "stale_snapshot_history",
        reasonMessage: (
          `Latest snapshot is ${latestSnapshotAgeMinutes.toFixed(1)}m old `
          + `(threshold ${(staleSnapshotThresholdSeconds / 60).toFixed(1)}m).`
        ),
        observedHistorySpanMinutes,
        observedPointCount: pointCount,
      }),
    };
  }

  const currentPrice = latest?.price ?? 0;
  const baselineRows = pickRowsWithinWindow(rows, anchorNow, 8 * 60 * 60);
  const windowScores = [];
  for (const window of RADAR_WINDOWS) {
    const windowRows = pickRowsWithinWindow(rows, anchorNow, window.seconds);
    const stretchScore = computeStretchScore(windowRows, currentPrice);
    const volatilitySpikeScore = computeVolatilitySpikeScore(
      windowRows,
      baselineRows.length >= 10 ? baselineRows : rows,
    );
    const bounceContextScore = computeBounceContextScore(
      windowRows,
      currentPrice,
      volatilitySpikeScore,
    );
    const hasMetrics = (
      stretchScore !== null
      && volatilitySpikeScore !== null
      && bounceContextScore !== null
    );
    windowScores.push({
      key: window.key,
      weight: window.weight,
      pointCount: windowRows.length,
      stretchScore,
      volatilitySpikeScore,
      bounceContextScore,
      hasMetrics,
    });
  }

  const windowsWithMetrics = windowScores.filter((row) => row.hasMetrics);
  if (windowsWithMetrics.length < 1) {
    return {
      symbol,
      ...buildInsufficient({
        reasonCode: "insufficient_window_coverage",
        reasonMessage: "Not enough window coverage for reliable volatility opportunity scoring.",
        observedHistorySpanMinutes,
        observedPointCount: pointCount,
      }),
    };
  }

  const stretchScore = weightedComponentAverage(windowScores, "stretchScore");
  const volatilitySpikeScore = weightedComponentAverage(windowScores, "volatilitySpikeScore");
  const bounceContextScore = weightedComponentAverage(windowScores, "bounceContextScore");
  const liquidityQualityScore = computeLiquidityQualityScore(latestSnapshot ?? null);

  const components = [
    { value: stretchScore, weight: 0.35 },
    { value: volatilitySpikeScore, weight: 0.35 },
    { value: bounceContextScore, weight: 0.2 },
    { value: liquidityQualityScore, weight: 0.1 },
  ].filter((row) => row.value !== null && Number.isFinite(row.value));

  const totalWeight = components.reduce((acc, row) => acc + row.weight, 0);
  const weightedScore = totalWeight <= 0
    ? null
    : components.reduce((acc, row) => acc + ((row.value * row.weight) / totalWeight), 0);
  const score = weightedScore === null ? null : clamp(weightedScore, 0, 100);
  const label = mapOpportunityLabel(score);
  const confidence = confidenceLabel({
    observedPointCount: pointCount,
    observedHistorySpanMinutes,
    windowsWithMetrics: windowsWithMetrics.length,
  });
  const reason = score === null
    ? "Insufficient data for volatility opportunity scoring."
    : buildReason({
        stretchScore,
        volatilitySpikeScore,
        bounceContextScore,
        liquidityQualityScore,
      });
  const confidenceScore = confidence === "HIGH" ? 85 : confidence === "MEDIUM" ? 62 : 35;
  const dataQualityStatus = (
    latestSnapshotAgeMinutes !== null && latestSnapshotAgeMinutes > (staleSnapshotThresholdSeconds / 60)
      ? "STALE"
      : windowsWithMetrics.length >= 3
        ? "GOOD"
        : "PARTIAL"
  );

  return {
    symbol,
    score: score === null ? null : Number(score.toFixed(3)),
    label,
    reason,
    confidence_label: confidence,
    stretch_score: stretchScore === null ? null : Number(stretchScore.toFixed(3)),
    volatility_spike_score:
      volatilitySpikeScore === null ? null : Number(volatilitySpikeScore.toFixed(3)),
    bounce_context_score:
      bounceContextScore === null ? null : Number(bounceContextScore.toFixed(3)),
    liquidity_quality_score:
      liquidityQualityScore === null ? null : Number(liquidityQualityScore.toFixed(3)),
    observed_history_span_minutes: Number(observedHistorySpanMinutes.toFixed(3)),
    observed_point_count: pointCount,
    insufficient_data: false,
    insufficient_reason_code: null,
    insufficient_reason_message: null,
    window_coverage: {
      total_windows: RADAR_WINDOWS.length,
      windows_with_metrics: windowsWithMetrics.length,
      keys_with_metrics: windowsWithMetrics.map((row) => row.key),
    },
    volatility_state: mapVolatilityState(score),
    volatility_score: score === null ? null : Number(score.toFixed(3)),
    components: {
      stretch_score: stretchScore === null ? null : Number(stretchScore.toFixed(3)),
      volatility_spike_score:
        volatilitySpikeScore === null ? null : Number(volatilitySpikeScore.toFixed(3)),
      bounce_context_score:
        bounceContextScore === null ? null : Number(bounceContextScore.toFixed(3)),
      liquidity_quality_score:
        liquidityQualityScore === null ? null : Number(liquidityQualityScore.toFixed(3)),
    },
    confidence_score: confidenceScore,
    data_quality: {
      status: dataQualityStatus,
      reason: dataQualityStatus === "GOOD" ? "ok" : "partial_window_coverage",
      sample_counts: {
        observed_points: pointCount,
        required_points: 10,
        windows_with_metrics: windowsWithMetrics.length,
        total_windows: RADAR_WINDOWS.length,
      },
      last_update_ts: latest?.tsEpoch ? new Date(latest.tsEpoch * 1000).toISOString() : null,
    },
  };
}

export {
  RADAR_WINDOWS,
  mapOpportunityLabel,
  analyzeVolatilityOpportunity,
};
