# Score/Stretch Observability Report (Last 12h)

- Source: `D:\Python-Codes\RevBot\.runtime\state\decision_audit.jsonl`
- Window rows: `11979`
- First row with any new field: `2026-04-12 18:40:59 UTC`
- Post-population rows: `492`

## New Field Population (Full 12h)

| Field | Non-null rows | Coverage |
|---|---:|---:|
| buy_score_actual | 377 | 3.15% |
| buy_score_threshold | 492 | 4.11% |
| buy_zscore_actual | 492 | 4.11% |
| buy_zscore_threshold | 492 | 4.11% |
| buy_stretch_actual | 492 | 4.11% |
| buy_stretch_threshold | 492 | 4.11% |
| buy_price_position_in_range | 0 | 0.00% |
| buy_zone_low | 492 | 4.11% |
| buy_zone_high | 492 | 4.11% |
| buy_route_name | 448 | 3.74% |

## New Field Population (Post-population subset)

| Field | Non-null rows | Coverage |
|---|---:|---:|
| buy_score_actual | 377 | 76.63% |
| buy_score_threshold | 492 | 100.00% |
| buy_zscore_actual | 492 | 100.00% |
| buy_zscore_threshold | 492 | 100.00% |
| buy_stretch_actual | 492 | 100.00% |
| buy_stretch_threshold | 492 | 100.00% |
| buy_price_position_in_range | 0 | 0.00% |
| buy_zone_low | 492 | 100.00% |
| buy_zone_high | 492 | 100.00% |
| buy_route_name | 448 | 91.06% |

## Score-Gate Rows Coverage

- `score_below_threshold` rows (full 12h): `2682`
- `score_below_threshold` rows (post-population): `85`
- `buy_score_actual` in post-population score rows: `27/85` (31.76%)
- `buy_score_threshold` in post-population score rows: `85/85` (100.00%)
- `buy_zscore_actual` in post-population score rows: `85/85` (100.00%)
- `buy_zscore_threshold` in post-population score rows: `85/85` (100.00%)
- `buy_stretch_actual` in post-population score rows: `85/85` (100.00%)
- `buy_stretch_threshold` in post-population score rows: `85/85` (100.00%)
- `buy_price_position_in_range` in post-population score rows: `0/85` (0.00%)
- `buy_zone_low` in post-population score rows: `85/85` (100.00%)
- `buy_zone_high` in post-population score rows: `85/85` (100.00%)
- `buy_route_name` in post-population score rows: `85/85` (100.00%)

## Interpretation
- Instrumentation is active in live runtime rows; low full-window percentages are diluted by pre-instrumentation rows in the same 12h window.
- `buy_price_position_in_range` remains unpopulated in post-population rows; this indicates upstream `range_position` is not present at audit emission time.
