# Buy-Zone Timed Experiment (Config-Only)

This experiment mutates only:

- `market_regime.preferred_buy_zone[1]` (`buy_zone_high`)

Risk/exits are not changed. The tool stores before/after metadata and can roll back automatically.

## Start (4h window, high=0.50)

```powershell
python crypto_bot/tools/buy_zone_experiment.py start --high 0.50 --hours 4 --tag "config_only_controlled_test"
```

## Monitor

```powershell
python crypto_bot/tools/buy_zone_experiment.py status
```

## Finalize + Auto Report + Rollback

```powershell
python crypto_bot/tools/buy_zone_experiment.py finalize
```

Outputs:

- `.runtime/state/reports/buy_zone_experiment_report_<timestamp>.json`
- `.runtime/state/reports/buy_zone_experiment_report_<timestamp>.md`

## Keep New Zone After Finalize

```powershell
python crypto_bot/tools/buy_zone_experiment.py finalize --keep
```

## Emergency Rollback

```powershell
python crypto_bot/tools/buy_zone_experiment.py rollback
```

