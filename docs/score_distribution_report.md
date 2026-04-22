# Score Distribution Report (Last 12h)

- Source: `D:\Python-Codes\RevBot\.runtime\state\decision_audit.jsonl`
- Window rows: `11979`
- `score_below_threshold` rows: `2682`
- First row with any new buy-observability field: `2026-04-12 18:40:59 UTC`
- Post-population rows: `492`
- Post-population `score_below_threshold` rows: `85`

## Coverage In `score_below_threshold` Rows

| Field | Full 12h coverage | Post-population coverage |
|---|---:|---:|
| buy_score_actual | 27/2682 (1.01%) | 27/85 (31.76%) |
| buy_score_threshold | 85/2682 (3.17%) | 85/85 (100.00%) |
| buy_stretch_actual | 85/2682 (3.17%) | 85/85 (100.00%) |
| buy_stretch_threshold | 85/2682 (3.17%) | 85/85 (100.00%) |
| buy_zscore_actual | 85/2682 (3.17%) | 85/85 (100.00%) |
| buy_zscore_threshold | 85/2682 (3.17%) | 85/85 (100.00%) |
| buy_price_position_in_range | 0/2682 (0.00%) | 0/85 (0.00%) |

## Distribution Summary (Post-population subset)

| Metric | Min | P25 | P50 | P75 | P90 | Max |
|---|---:|---:|---:|---:|---:|---:|
| buy_score_actual | 11.00 | 11.00 | 11.00 | 11.00 | 11.00 | 33.00 |
| buy_score_threshold | 50.00 | 50.00 | 50.00 | 50.00 | 50.00 | 50.00 |
| buy_stretch_actual | -11880.8462 | -32.5867 | -32.3611 | -6.6356 | -3.9572 | -3.9572 |
| buy_stretch_threshold | -1.3000 | -1.3000 | -1.3000 | -1.3000 | -1.3000 | -1.3000 |
| buy_zscore_actual | -11880.8462 | -32.5867 | -32.3611 | -6.6356 | -3.9572 | -3.9572 |
| buy_zscore_threshold | -1.3000 | -1.3000 | -1.3000 | -1.3000 | -1.3000 | -1.3000 |
| buy_price_position_in_range | N/A | N/A | N/A | N/A | N/A | N/A |

## Score Buckets (Post-population subset)

| Bucket | Count | % |
|---|---:|---:|
| 10-14 | 26 | 96.30% |
| 30-34 | 1 | 3.70% |

## Gap To Score Threshold (Post-population subset)

| Gap | Count | % |
|---|---:|---:|
| <1 | 0 | 0.00% |
| 1-2 | 0 | 0.00% |
| 2-5 | 0 | 0.00% |
| >=5 | 27 | 100.00% |

## Route Mix (Post-population subset)

| Route | Count | % |
|---|---:|---:|
| mean_reversion | 85 | 100.00% |

## Top Symbols (Post-population subset)

| Symbol | Count | % |
|---|---:|---:|
| XLM-USD | 43 | 50.59% |
| XTZ-USD | 26 | 30.59% |
| UNI-USD | 13 | 15.29% |
| AAVE-USD | 1 | 1.18% |
| ADA-USD | 1 | 1.18% |
| APT-USD | 1 | 1.18% |
