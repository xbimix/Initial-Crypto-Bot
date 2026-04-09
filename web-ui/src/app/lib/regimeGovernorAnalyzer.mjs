import { buildCandlesFromSnapshots, detectSwingPivots } from "./waveZoneAnalyzer.mjs";

const REGIME_GOVERNOR_TIMEFRAMES = [
  { key: "1h", windowSeconds: 1 * 3600, pivotWidth: 2, weight: 0.08 },
  { key: "4h", windowSeconds: 4 * 3600, pivotWidth: 3, weight: 0.14 },
  { key: "8h", windowSeconds: 8 * 3600, pivotWidth: 3, weight: 0.16 },
  { key: "12h", windowSeconds: 12 * 3600, pivotWidth: 3, weight: 0.14 },
  { key: "16h", windowSeconds: 16 * 3600, pivotWidth: 3, weight: 0.16 },
  { key: "24h", windowSeconds: 24 * 3600, pivotWidth: 3, weight: 0.17 },
  { key: "3d", windowSeconds: 3 * 24 * 3600, pivotWidth: 4, weight: 0.09 },
  { key: "7d", windowSeconds: 7 * 24 * 3600, pivotWidth: 5, weight: 0.06 },
];

const OUTPUT_REGIME_MEAN_REVERSION = "MEAN_REVERSION_FRIENDLY";
const OUTPUT_REGIME_TREND = "TREND_CONTINUATION";
const OUTPUT_REGIME_BREAKOUT = "BREAKOUT_EXPANSION";
const OUTPUT_REGIME_MIXED = "MIXED_OR_UNCLEAR";

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function average(values) {
  if (!Array.isArray(values) || values.length === 0) {
    return 0;
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
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
    .filter((row) => Number.isFinite(row.tsEpoch) && row.tsEpoch > 0 && Number.isFinite(row.price) && row.price > 0)
    .sort((left, right) => left.tsEpoch - right.tsEpoch);
}

function returnsPct(points) {
  const output = [];
  for (let index = 1; index < points.length; index += 1) {
    const prev = points[index - 1]?.price ?? 0;
    const curr = points[index]?.price ?? 0;
    if (prev <= 0 || curr <= 0) {
      continue;
    }
    output.push(((curr - prev) / prev) * 100);
  }
  return output;
}

function stddev(values) {
  if (!Array.isArray(values) || values.length < 2) {
    return 0;
  }
  const mean = average(values);
  const variance = values.reduce((sum, value) => sum + ((value - mean) ** 2), 0) / values.length;
  return Math.sqrt(Math.max(variance, 0));
}

function confidenceLabel(score) {
  if (!Number.isFinite(score)) {
    return "LOW";
  }
  if (score >= 72) {
    return "HIGH";
  }
  if (score >= 48) {
    return "MEDIUM";
  }
  return "LOW";
}

function computeMedianZone(pivots, referencePrice, amplitudePct) {
  if (!Array.isArray(pivots) || pivots.length === 0) {
    return null;
  }
  const prices = pivots.map((pivot) => Number(pivot.price)).filter((value) => Number.isFinite(value) && value > 0);
  if (prices.length === 0) {
    return null;
  }
  const sorted = [...prices].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  const median = sorted.length % 2 === 0
    ? (sorted[middle - 1] + sorted[middle]) / 2
    : sorted[middle];
  const absDeviations = sorted.map((value) => Math.abs(value - median));
  const medianAbsDeviation = average(absDeviations);
  const reference = referencePrice > 0 ? referencePrice : median;
  const pctWidth = clamp(Math.max(0.25, amplitudePct * 0.1) / 100, 0.0025, 0.03);
  const halfWidth = Math.max(reference * pctWidth, medianAbsDeviation * 1.6, reference * 0.0015);
  return {
    center: Number(median.toFixed(8)),
    min: Number((median - halfWidth).toFixed(8)),
    max: Number((median + halfWidth).toFixed(8)),
    pivotCount: prices.length,
  };
}

function countHigherLower(pivots) {
  if (!Array.isArray(pivots) || pivots.length < 2) {
    return { higher: 0, lower: 0 };
  }
  let higher = 0;
  let lower = 0;
  for (let index = 1; index < pivots.length; index += 1) {
    const prev = Number(pivots[index - 1]?.price ?? 0);
    const curr = Number(pivots[index]?.price ?? 0);
    if (!Number.isFinite(prev) || !Number.isFinite(curr)) {
      continue;
    }
    if (curr > prev) {
      higher += 1;
    } else if (curr < prev) {
      lower += 1;
    }
  }
  return { higher, lower };
}

function classifyStructure({
  higherHighs,
  lowerHighs,
  higherLows,
  lowerLows,
  waveSlopePct,
  waveAmplitudePct,
  currentPrice,
  highPrice,
  lowPrice,
}) {
  const absSlope = Math.abs(waveSlopePct);
  const nearTop = highPrice > 0 && currentPrice >= highPrice * 0.985;
  const nearBottom = lowPrice > 0 && currentPrice <= lowPrice * 1.015;

  if (higherHighs >= 2 && higherLows >= 2 && waveSlopePct >= 0.18) {
    return "UPTREND";
  }
  if (lowerHighs >= 2 && lowerLows >= 2 && waveSlopePct <= -0.18) {
    return "DOWNTREND";
  }
  if (
    waveAmplitudePct >= 2.5
    && absSlope >= 0.25
    && ((nearTop && higherHighs >= 1) || (nearBottom && lowerLows >= 1))
  ) {
    return "BREAKOUT_SETUP";
  }
  if (
    absSlope <= 0.28
    && waveAmplitudePct >= 0.3
    && waveAmplitudePct <= 10
    && Math.abs((higherHighs + higherLows) - (lowerHighs + lowerLows)) <= 2
  ) {
    return "RANGE";
  }
  return "UNCLEAR";
}

function classifyVolatilityState(timeframeRows, baselineRows) {
  const tfReturns = returnsPct(timeframeRows);
  const baseReturns = returnsPct(baselineRows);
  if (tfReturns.length < 5 || baseReturns.length < 8) {
    return "NORMAL";
  }
  const tfVol = stddev(tfReturns);
  const baseVol = Math.max(stddev(baseReturns), 1e-8);
  const ratio = tfVol / baseVol;
  if (ratio >= 1.55) {
    return "HIGH_VOL";
  }
  if (ratio <= 0.7) {
    return "LOW_VOL";
  }
  return "NORMAL";
}

function computeComponentScores({
  structureClass,
  volatilityState,
  waveSlopePct,
  waveAmplitudePct,
  higherHighs,
  lowerHighs,
  higherLows,
  lowerLows,
  currentPrice,
  highPrice,
  lowPrice,
}) {
  const absSlope = Math.abs(waveSlopePct);
  const trendImbalance = Math.abs((higherHighs + higherLows) - (lowerHighs + lowerLows));
  const balanceRatio = 1 - clamp(trendImbalance / 6, 0, 1);
  const amplitudeNorm = clamp(waveAmplitudePct / 8, 0, 1);
  const slopeNorm = clamp(absSlope / 1.2, 0, 1);
  const nearTop = highPrice > 0 && currentPrice >= highPrice * 0.986;
  const nearBottom = lowPrice > 0 && currentPrice <= lowPrice * 1.014;

  const trendScore = clamp(
    (
      (structureClass === "UPTREND" || structureClass === "DOWNTREND" ? 0.45 : 0.1)
      + (0.35 * slopeNorm)
      + (0.20 * (1 - balanceRatio))
    ) * 100,
    0,
    100,
  );

  const rangeScore = clamp(
    (
      (structureClass === "RANGE" ? 0.50 : 0.12)
      + (0.30 * (1 - slopeNorm))
      + (0.20 * balanceRatio)
    ) * 100,
    0,
    100,
  );

  const breakoutScore = clamp(
    (
      (structureClass === "BREAKOUT_SETUP" ? 0.52 : 0.1)
      + (volatilityState === "HIGH_VOL" ? 0.18 : 0)
      + (0.22 * amplitudeNorm)
      + (nearTop || nearBottom ? 0.08 : 0)
    ) * 100,
    0,
    100,
  );

  const mixedScore = clamp(
    (
      (structureClass === "UNCLEAR" ? 0.55 : 0.14)
      + (volatilityState === "LOW_VOL" ? 0.12 : 0)
      + (0.18 * (1 - Math.max(trendScore, rangeScore, breakoutScore) / 100))
      + (0.15 * balanceRatio)
    ) * 100,
    0,
    100,
  );

  return {
    trendScore: Number(trendScore.toFixed(3)),
    rangeScore: Number(rangeScore.toFixed(3)),
    breakoutScore: Number(breakoutScore.toFixed(3)),
    mixedScore: Number(mixedScore.toFixed(3)),
    trend_score: Number(trendScore.toFixed(3)),
    range_score: Number(rangeScore.toFixed(3)),
    breakout_score: Number(breakoutScore.toFixed(3)),
    mixed_score: Number(mixedScore.toFixed(3)),
  };
}

function classifyParticipationState(latestSnapshot) {
  if (!latestSnapshot || typeof latestSnapshot !== "object") {
    return "NORMAL";
  }
  const spreadBps = Number(latestSnapshot.spreadBps ?? latestSnapshot.spread_bps ?? NaN);
  const quality = String(
    latestSnapshot.quality
    ?? latestSnapshot.data_quality_reason
    ?? "ok",
  ).toLowerCase();
  if ((Number.isFinite(spreadBps) && spreadBps > 150) || (quality && quality !== "ok")) {
    return "THIN";
  }
  return "NORMAL";
}

function mapSuggestedRegime({ structureClass, volatilityState, waveSlopePct }) {
  if (structureClass === "RANGE" && volatilityState !== "HIGH_VOL") {
    return OUTPUT_REGIME_MEAN_REVERSION;
  }
  if ((structureClass === "UPTREND" || structureClass === "DOWNTREND") && Math.abs(waveSlopePct) >= 0.18) {
    return OUTPUT_REGIME_TREND;
  }
  if (
    structureClass === "BREAKOUT_SETUP"
    || (volatilityState === "HIGH_VOL" && Math.abs(waveSlopePct) >= 0.3)
  ) {
    return OUTPUT_REGIME_BREAKOUT;
  }
  return OUTPUT_REGIME_MIXED;
}

function computeTimeframeConfidence({
  observedPointCount,
  observedHistorySpanMinutes,
  requiredSpanMinutes,
  structureClass,
  higherHighs,
  lowerHighs,
  higherLows,
  lowerLows,
  waveSlopePct,
  participationState,
  suggestedRegime,
}) {
  const depthNorm = clamp(observedPointCount / 120, 0, 1);
  const spanNorm = clamp(observedHistorySpanMinutes / Math.max(requiredSpanMinutes, 1), 0, 1);
  const trendImbalance = Math.abs((higherHighs + higherLows) - (lowerHighs + lowerLows));
  const structureNorm = structureClass === "UNCLEAR"
    ? 0.2
    : clamp((trendImbalance + Math.abs(waveSlopePct) * 2.2) / 5, 0.3, 1);
  const participationPenalty = participationState === "THIN" ? 0.15 : 0;
  const mixedPenalty = suggestedRegime === OUTPUT_REGIME_MIXED ? 0.18 : 0;
  const score = (
    (0.35 * depthNorm)
    + (0.30 * spanNorm)
    + (0.35 * structureNorm)
    - participationPenalty
    - mixedPenalty
  ) * 100;
  return clamp(score, 0, 100);
}

function buildInsufficientResult({
  reasonCode,
  reasonMessage,
  observedPointCount,
  observedHistorySpanMinutes,
}) {
  const dataQuality = {
    status: reasonCode === "unsupported_timeframe" ? "UNSUPPORTED_WINDOW" : "INSUFFICIENT",
    reason: reasonCode,
    sample_counts: {
      observed_points: observedPointCount,
      required_points: 10,
    },
  };
  return {
    insufficientData: true,
    insufficientReasonCode: reasonCode,
    insufficientReasonMessage: reasonMessage,
    observedPointCount,
    observedHistorySpanMinutes: Number(observedHistorySpanMinutes.toFixed(3)),
    wave: {
      swingHighCount: 0,
      swingLowCount: 0,
      higherHighsCount: 0,
      lowerHighsCount: 0,
      higherLowsCount: 0,
      lowerLowsCount: 0,
      waveSlopePct: 0,
      waveAmplitudePct: 0,
    },
    medianHighZone: null,
    medianLowZone: null,
    structureClass: "UNCLEAR",
    volatilityState: "NORMAL",
    participationState: "NORMAL",
    suggestedRegime: OUTPUT_REGIME_MIXED,
    componentScores: {
      trendScore: 0,
      rangeScore: 0,
      breakoutScore: 0,
      mixedScore: 100,
      trend_score: 0,
      range_score: 0,
      breakout_score: 0,
      mixed_score: 100,
    },
    stabilityScore: 0,
    stability_score: 0,
    persistenceScore: 0,
    persistence_score: 0,
    stabilityInferred: true,
    stability_inferred: true,
    persistenceInferred: true,
    persistence_inferred: true,
    confidenceScore: 0,
    confidenceLabel: "LOW",
    data_quality: dataQuality,
  };
}

function analyzeTimeframe({
  timeframe,
  points,
  baselineRows,
  currentPrice,
  nowEpoch,
  latestSnapshot,
}) {
  const rows = points.filter(
    (row) => row.tsEpoch >= (nowEpoch - timeframe.windowSeconds) && row.tsEpoch <= nowEpoch,
  );
  const observedPointCount = rows.length;
  const observedHistorySpanMinutes = rows.length >= 2
    ? Math.max((rows[rows.length - 1].tsEpoch - rows[0].tsEpoch) / 60, 0)
    : 0;
  const requiredSpanMinutes = timeframe.windowSeconds / 60;
  if (observedPointCount < 18) {
    return buildInsufficientResult({
      reasonCode: "insufficient_point_count",
      reasonMessage: `Observed ${observedPointCount} points, need at least 18 for ${timeframe.key}.`,
      observedPointCount,
      observedHistorySpanMinutes,
    });
  }

  if (observedHistorySpanMinutes < requiredSpanMinutes * 0.22) {
    return buildInsufficientResult({
      reasonCode: "insufficient_history_span",
      reasonMessage: (
        `Observed span ${observedHistorySpanMinutes.toFixed(1)}m is below `
        + `${(requiredSpanMinutes * 0.22).toFixed(1)}m minimum for ${timeframe.key}.`
      ),
      observedPointCount,
      observedHistorySpanMinutes,
    });
  }

  const bucketSeconds = Math.max(60, Math.round(timeframe.windowSeconds / 120));
  const candles = buildCandlesFromSnapshots(rows, bucketSeconds);
  if (candles.length < Math.max(14, timeframe.pivotWidth * 3)) {
    return buildInsufficientResult({
      reasonCode: "insufficient_candle_count",
      reasonMessage: `Observed ${candles.length} candles, need more for ${timeframe.key}.`,
      observedPointCount,
      observedHistorySpanMinutes,
    });
  }

  const pivots = detectSwingPivots(candles, timeframe.pivotWidth);
  if (pivots.highs.length === 0 && pivots.lows.length === 0) {
    return buildInsufficientResult({
      reasonCode: "no_valid_pivots",
      reasonMessage: `No valid pivots detected for ${timeframe.key}.`,
      observedPointCount,
      observedHistorySpanMinutes,
    });
  }

  const highsProgression = countHigherLower(pivots.highs);
  const lowsProgression = countHigherLower(pivots.lows);
  const firstOpen = Number(candles[0]?.open ?? 0);
  const lastClose = Number(candles[candles.length - 1]?.close ?? 0);
  const highPrice = Math.max(...candles.map((row) => Number(row.high ?? 0)));
  const lowPrice = Math.min(...candles.map((row) => Number(row.low ?? Number.MAX_VALUE)));
  const waveSlopePct = firstOpen > 0 ? ((lastClose - firstOpen) / firstOpen) * 100 : 0;
  const waveAmplitudePct = (
    highPrice > 0
    && lowPrice > 0
    && highPrice > lowPrice
  )
    ? ((highPrice - lowPrice) / ((highPrice + lowPrice) / 2)) * 100
    : 0;
  const medianHighZone = computeMedianZone(pivots.highs, currentPrice, waveAmplitudePct);
  const medianLowZone = computeMedianZone(pivots.lows, currentPrice, waveAmplitudePct);
  const structureClass = classifyStructure({
    higherHighs: highsProgression.higher,
    lowerHighs: highsProgression.lower,
    higherLows: lowsProgression.higher,
    lowerLows: lowsProgression.lower,
    waveSlopePct,
    waveAmplitudePct,
    currentPrice,
    highPrice,
    lowPrice,
  });
  const volatilityState = classifyVolatilityState(rows, baselineRows);
  const participationState = classifyParticipationState(latestSnapshot);
  const suggestedRegime = mapSuggestedRegime({
    structureClass,
    volatilityState,
    waveSlopePct,
  });
  const componentScores = computeComponentScores({
    structureClass,
    volatilityState,
    waveSlopePct,
    waveAmplitudePct,
    higherHighs: highsProgression.higher,
    lowerHighs: highsProgression.lower,
    higherLows: lowsProgression.higher,
    lowerLows: lowsProgression.lower,
    currentPrice,
    highPrice,
    lowPrice,
  });
  const confidenceScore = computeTimeframeConfidence({
    observedPointCount,
    observedHistorySpanMinutes,
    requiredSpanMinutes,
    structureClass,
    higherHighs: highsProgression.higher,
    lowerHighs: highsProgression.lower,
    higherLows: lowsProgression.higher,
    lowerLows: lowsProgression.lower,
    waveSlopePct,
    participationState,
    suggestedRegime,
  });
  const sortedComponentValues = [
    componentScores.trendScore,
    componentScores.rangeScore,
    componentScores.breakoutScore,
    componentScores.mixedScore,
  ].sort((left, right) => right - left);
  const componentDominance = (sortedComponentValues[0] ?? 0) - (sortedComponentValues[1] ?? 0);
  const stabilityScore = clamp(
    (componentDominance * 0.6) + (confidenceScore * 0.4),
    0,
    100,
  );

  return {
    insufficientData: false,
    insufficientReasonCode: null,
    insufficientReasonMessage: null,
    observedPointCount,
    observedHistorySpanMinutes: Number(observedHistorySpanMinutes.toFixed(3)),
    wave: {
      swingHighCount: pivots.highs.length,
      swingLowCount: pivots.lows.length,
      higherHighsCount: highsProgression.higher,
      lowerHighsCount: highsProgression.lower,
      higherLowsCount: lowsProgression.higher,
      lowerLowsCount: lowsProgression.lower,
      waveSlopePct: Number(waveSlopePct.toFixed(4)),
      waveAmplitudePct: Number(waveAmplitudePct.toFixed(4)),
    },
    medianHighZone,
    medianLowZone,
    structureClass,
    volatilityState,
    participationState,
    suggestedRegime,
    componentScores,
    stabilityScore: Number(stabilityScore.toFixed(3)),
    stability_score: Number(stabilityScore.toFixed(3)),
    confidenceScore: Number(confidenceScore.toFixed(3)),
    confidenceLabel: confidenceLabel(confidenceScore),
  };
}

function weightedLabel(values, fallback) {
  if (!Array.isArray(values) || values.length === 0) {
    return fallback;
  }
  const bucket = new Map();
  for (const row of values) {
    bucket.set(row.value, (bucket.get(row.value) ?? 0) + row.weight);
  }
  const ranked = Array.from(bucket.entries()).sort((left, right) => right[1] - left[1]);
  return ranked[0]?.[0] ?? fallback;
}

function buildExplanation({ suggestedRegime, structureBias, volatilityState, participationState }) {
  if (suggestedRegime === OUTPUT_REGIME_MEAN_REVERSION) {
    return (
      "Range-like structure across weighted windows with repeated median-zone reversion and controlled volatility."
    );
  }
  if (suggestedRegime === OUTPUT_REGIME_TREND) {
    return (
      "Directional wave structure (higher-high/lower-low bias) with continuation profile across short and medium windows."
    );
  }
  if (suggestedRegime === OUTPUT_REGIME_BREAKOUT) {
    return (
      "Expansion-style structure with elevated volatility and directional pressure near median high/low boundaries."
    );
  }
  return (
    `Mixed structure (${structureBias}) with ${volatilityState.toLowerCase()} volatility and `
    + `${participationState.toLowerCase()} participation. Keep default mean-reversion path.`
  );
}

/**
 * @param {{
 *   symbol: string,
 *   pricePoints: Array<{ tsEpoch: number, price: number }>,
 *   latestSnapshot?: Record<string, unknown> | null,
 *   nowEpoch?: number,
 * }} args
 */
function analyzeRegimeGovernor({
  symbol,
  pricePoints,
  latestSnapshot = null,
  nowEpoch,
}) {
  const rows = normalizePricePoints(pricePoints);
  const latestPoint = rows[rows.length - 1] ?? null;
  const anchorNow = Number.isFinite(nowEpoch) && nowEpoch > 0
    ? nowEpoch
    : (latestPoint?.tsEpoch ?? (Date.now() / 1000));
  const currentPrice = latestPoint?.price ?? 0;
  const baselineRows = rows.filter((row) => row.tsEpoch >= anchorNow - (7 * 24 * 3600) && row.tsEpoch <= anchorNow);
  const timeframeSummary = {};
  const regimeBuckets = new Map([
    [OUTPUT_REGIME_MEAN_REVERSION, 0],
    [OUTPUT_REGIME_TREND, 0],
    [OUTPUT_REGIME_BREAKOUT, 0],
    [OUTPUT_REGIME_MIXED, 0],
  ]);
  const aggregateComponentTotals = {
    trendScore: 0,
    rangeScore: 0,
    breakoutScore: 0,
    mixedScore: 0,
  };
  const aggregateStability = {
    weightedTotal: 0,
    weight: 0,
  };
  const structureVotes = [];
  const volatilityVotes = [];
  const participationVotes = [];
  let totalWeight = 0;

  for (const timeframe of REGIME_GOVERNOR_TIMEFRAMES) {
    const row = analyzeTimeframe({
      timeframe,
      points: rows,
      baselineRows: baselineRows.length > 0 ? baselineRows : rows,
      currentPrice,
      nowEpoch: anchorNow,
      latestSnapshot,
    });
    timeframeSummary[timeframe.key] = {
      ...row,
      data_quality: row.insufficientData
        ? {
            status: "INSUFFICIENT",
            reason: row.insufficientReasonCode ?? "insufficient_window_data",
            sample_counts: {
              observed_points: row.observedPointCount ?? 0,
              required_points: 10,
            },
          }
        : {
            status: "GOOD",
            reason: "ok",
            sample_counts: {
              observed_points: row.observedPointCount ?? 0,
              required_points: 10,
            },
          },
    };
    if (row.insufficientData) {
      continue;
    }

    const confidenceWeight = timeframe.weight * (row.confidenceScore / 100);
    regimeBuckets.set(
      row.suggestedRegime,
      (regimeBuckets.get(row.suggestedRegime) ?? 0) + confidenceWeight,
    );
    aggregateComponentTotals.trendScore += (row.componentScores?.trendScore ?? 0) * confidenceWeight;
    aggregateComponentTotals.rangeScore += (row.componentScores?.rangeScore ?? 0) * confidenceWeight;
    aggregateComponentTotals.breakoutScore += (row.componentScores?.breakoutScore ?? 0) * confidenceWeight;
    aggregateComponentTotals.mixedScore += (row.componentScores?.mixedScore ?? 0) * confidenceWeight;
    aggregateStability.weightedTotal += (row.stabilityScore ?? 0) * confidenceWeight;
    aggregateStability.weight += confidenceWeight;
    structureVotes.push({ value: row.structureClass, weight: confidenceWeight });
    volatilityVotes.push({ value: row.volatilityState, weight: confidenceWeight });
    participationVotes.push({ value: row.participationState, weight: confidenceWeight });
    totalWeight += confidenceWeight;
  }

  const rankedRegimes = Array.from(regimeBuckets.entries()).sort((left, right) => right[1] - left[1]);
  const topRegime = rankedRegimes[0]?.[0] ?? OUTPUT_REGIME_MIXED;
  const topWeight = rankedRegimes[0]?.[1] ?? 0;
  const secondWeight = rankedRegimes[1]?.[1] ?? 0;
  const dominanceDelta = topWeight - secondWeight;
  const normalizedConfidence = totalWeight > 0
    ? clamp((topWeight / totalWeight) * 100, 0, 100)
    : 0;
  const suggestedRegime = (totalWeight <= 0 || normalizedConfidence < 45 || dominanceDelta < 0.03)
    ? OUTPUT_REGIME_MIXED
    : topRegime;
  const confidenceScore = Number(
    clamp(
      suggestedRegime === OUTPUT_REGIME_MIXED ? normalizedConfidence * 0.9 : normalizedConfidence,
      0,
      100,
    ).toFixed(3),
  );
  const structureBiasRaw = weightedLabel(structureVotes, "UNCLEAR");
  const structureBias = structureBiasRaw === "UPTREND"
    ? "TREND_UP"
    : structureBiasRaw === "DOWNTREND"
      ? "TREND_DOWN"
      : structureBiasRaw;
  const volatilityState = weightedLabel(volatilityVotes, "NORMAL");
  const participationState = weightedLabel(participationVotes, "NORMAL");
  const componentScores = totalWeight > 0
    ? {
        trendScore: Number((aggregateComponentTotals.trendScore / totalWeight).toFixed(3)),
        rangeScore: Number((aggregateComponentTotals.rangeScore / totalWeight).toFixed(3)),
        breakoutScore: Number((aggregateComponentTotals.breakoutScore / totalWeight).toFixed(3)),
        mixedScore: Number((aggregateComponentTotals.mixedScore / totalWeight).toFixed(3)),
      }
    : {
        trendScore: 0,
        rangeScore: 0,
        breakoutScore: 0,
        mixedScore: 100,
      };
  const stabilityScore = aggregateStability.weight > 0
    ? Number((aggregateStability.weightedTotal / aggregateStability.weight).toFixed(3))
    : 0;
  const topShare = totalWeight > 0 ? clamp(topWeight / totalWeight, 0, 1) : 0;
  const dominanceNorm = totalWeight > 0 ? clamp(dominanceDelta / totalWeight, 0, 1) : 0;
  const persistenceScore = Number(
    clamp(
      (0.55 * (topShare * 100)) + (0.25 * (dominanceNorm * 100)) + (0.20 * stabilityScore),
      0,
      100,
    ).toFixed(3),
  );
  const inferredScores = totalWeight <= 0;
  const analysisAnchorAt = new Date(anchorNow * 1000).toISOString();

  return {
    symbol,
    suggestedRegime,
    confidenceScore,
    confidenceLabel: confidenceLabel(confidenceScore),
    detectionSource: "advisory_multitimeframe",
    analysisAnchorEpoch: Number(anchorNow.toFixed(3)),
    analysisAnchorAt,
    componentScores: {
      ...componentScores,
      trend_score: componentScores.trendScore,
      range_score: componentScores.rangeScore,
      breakout_score: componentScores.breakoutScore,
      mixed_score: componentScores.mixedScore,
    },
    stabilityScore,
    stability_score: stabilityScore,
    persistenceScore,
    persistence_score: persistenceScore,
    stabilityInferred: inferredScores,
    stability_inferred: inferredScores,
    persistenceInferred: inferredScores,
    persistence_inferred: inferredScores,
    explanation: buildExplanation({
      suggestedRegime,
      structureBias,
      volatilityState,
      participationState,
    }),
    components: {
      structureBias,
      volatilityState,
      participationState,
    },
    timeframeSummary,
    data_quality: {
      status: totalWeight > 0.45 ? "GOOD" : totalWeight > 0.2 ? "PARTIAL" : "INSUFFICIENT",
      reason: totalWeight > 0 ? "window_coverage" : "no_supported_windows",
      sample_counts: {
        windows_with_signal: structureVotes.length,
        total_windows: REGIME_GOVERNOR_TIMEFRAMES.length,
      },
      last_update_ts: analysisAnchorAt,
    },
    dataQualityNote: (
      "Advisory-only regime inference from observed snapshot history. "
      + "Not execution logic or guaranteed prediction."
    ),
  };
}

export {
  REGIME_GOVERNOR_TIMEFRAMES,
  OUTPUT_REGIME_MEAN_REVERSION,
  OUTPUT_REGIME_TREND,
  OUTPUT_REGIME_BREAKOUT,
  OUTPUT_REGIME_MIXED,
  analyzeRegimeGovernor,
};
