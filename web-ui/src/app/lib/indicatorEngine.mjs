function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function toCandles(pricePoints, bucketSeconds = 60) {
  if (!Array.isArray(pricePoints) || pricePoints.length === 0) {
    return [];
  }
  const bucket = Math.max(1, Math.trunc(bucketSeconds));
  const buckets = new Map();
  for (const row of pricePoints) {
    const ts = Number(row?.tsEpoch ?? 0);
    const price = Number(row?.price ?? 0);
    if (!Number.isFinite(ts) || ts <= 0 || !Number.isFinite(price) || price <= 0) {
      continue;
    }
    const key = Math.floor(ts / bucket) * bucket;
    const existing = buckets.get(key);
    if (!existing) {
      buckets.set(key, {
        tsEpoch: key,
        open: price,
        high: price,
        low: price,
        close: price,
        volume: 1,
      });
      continue;
    }
    existing.high = Math.max(existing.high, price);
    existing.low = Math.min(existing.low, price);
    existing.close = price;
    existing.volume += 1;
  }
  return Array.from(buckets.values()).sort((a, b) => a.tsEpoch - b.tsEpoch);
}

function atr(candles, period = 14) {
  if (!Array.isArray(candles) || candles.length < period + 1) {
    return null;
  }
  const tr = [];
  for (let i = 1; i < candles.length; i += 1) {
    const h = candles[i].high;
    const l = candles[i].low;
    const prevClose = candles[i - 1].close;
    tr.push(Math.max(h - l, Math.abs(h - prevClose), Math.abs(l - prevClose)));
  }
  if (tr.length < period) {
    return null;
  }
  const slice = tr.slice(-period);
  return slice.reduce((sum, value) => sum + value, 0) / slice.length;
}

function rsi(candles, period = 14) {
  if (!Array.isArray(candles) || candles.length < period + 1) {
    return null;
  }
  let gains = 0;
  let losses = 0;
  for (let i = candles.length - period; i < candles.length; i += 1) {
    const prev = candles[i - 1].close;
    const curr = candles[i].close;
    const delta = curr - prev;
    if (delta > 0) {
      gains += delta;
    } else {
      losses += Math.abs(delta);
    }
  }
  const avgGain = gains / period;
  const avgLoss = losses / period;
  if (avgLoss <= 0) {
    return 100;
  }
  const rs = avgGain / avgLoss;
  return 100 - (100 / (1 + rs));
}

function returnVolatility(candles, period = 20) {
  if (!Array.isArray(candles) || candles.length < period + 1) {
    return null;
  }
  const values = [];
  for (let i = candles.length - period; i < candles.length; i += 1) {
    const prev = candles[i - 1].close;
    const curr = candles[i].close;
    if (prev <= 0) {
      continue;
    }
    values.push((curr - prev) / prev);
  }
  if (values.length < 3) {
    return null;
  }
  const mean = values.reduce((s, x) => s + x, 0) / values.length;
  const variance = values.reduce((s, x) => s + ((x - mean) ** 2), 0) / values.length;
  return Math.sqrt(Math.max(variance, 0));
}

function buildIndicatorBundle({
  symbol,
  pricePoints,
  wallClockEpoch = Date.now() / 1000,
}) {
  const candles = toCandles(pricePoints, 60);
  const latest = candles[candles.length - 1] ?? null;
  const earliest = candles[0] ?? null;
  const spanMinutes = (latest && earliest) ? Math.max((latest.tsEpoch - earliest.tsEpoch) / 60, 0) : 0;
  const atrValue = atr(candles, 14);
  const rsiValue = rsi(candles, 14);
  const volValue = returnVolatility(candles, 20);
  const recent = candles.slice(-20);
  const recentHigh = recent.length > 0 ? Math.max(...recent.map((row) => row.high)) : null;
  const recentLow = recent.length > 0 ? Math.min(...recent.map((row) => row.low)) : null;
  const latestClose = latest?.close ?? null;
  const prevClose = candles.length >= 2 ? candles[candles.length - 2].close : null;
  const momentum = (latestClose !== null && prevClose !== null && prevClose > 0)
    ? ((latestClose - prevClose) / prevClose)
    : null;
  const rangePct = (latest && latest.close > 0)
    ? ((latest.high - latest.low) / latest.close)
    : null;
  const volNorm = volValue === null ? null : clamp((volValue / 0.02) * 100, 0, 100);
  const compressionScore = volNorm === null ? null : (100 - volNorm);
  const expansionScore = volNorm;
  const vwap = candles.length > 0
    ? candles.reduce((sum, row) => sum + row.close * row.volume, 0)
      / Math.max(candles.reduce((sum, row) => sum + row.volume, 0), 1e-9)
    : null;

  const ageMinutes = latest ? Math.max((wallClockEpoch - latest.tsEpoch) / 60, 0) : null;
  let quality = "GOOD";
  let reason = "ok";
  if (candles.length < 30) {
    quality = candles.length > 0 ? "PARTIAL" : "INSUFFICIENT";
    reason = candles.length > 0 ? "insufficient_samples" : "no_samples";
  }
  if (ageMinutes !== null && ageMinutes > 20) {
    quality = "STALE";
    reason = "stale_history";
  }

  return {
    symbol,
    atr: atrValue,
    rsi: rsiValue,
    returnVolatility: volValue,
    candleRangePct: rangePct,
    momentum,
    recentHigh,
    recentLow,
    compressionScore,
    expansionScore,
    vwap,
    observedPointCount: candles.length,
    observedHistorySpanMinutes: Number(spanMinutes.toFixed(3)),
    dataQuality: {
      status: quality,
      reason,
      sampleCounts: {
        observed: candles.length,
        required: 30,
      },
      lastUpdateTs: latest ? new Date(latest.tsEpoch * 1000).toISOString() : null,
    },
  };
}

export {
  toCandles,
  buildIndicatorBundle,
};
