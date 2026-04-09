# Keep Manifest

Date: 2026-04-06

## Must Keep (Runtime Critical)
- `crypto_bot/`
- `web-ui/`
- `scripts/` (runtime/deploy helpers)
- `.github/workflows/`
- `.runtime/state/` (live runtime data)
- `crypto_bot/utils/state_paths.py`
- `crypto_bot/utils/config_loader.py`
- `crypto_bot/main.py`
- `crypto_bot/control/`
- `crypto_bot/strategy/`
- `crypto_bot/risk/`
- `crypto_bot/trading/`

## Must Keep (Project Integrity)
- `docs/` active docs
- `pytest.ini`
- `.gitignore`
- `AGENTS.MD`

## Keep But Exclude From VCS
- `.venv/`
- `.runtime/`
- temp/cache directories listed in `.gitignore`
