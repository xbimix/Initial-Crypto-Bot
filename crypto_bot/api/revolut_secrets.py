from __future__ import annotations

import os
from pathlib import Path

from utils.logger import setup_logger

logger = setup_logger("revolut_secrets")

API_DIR = Path(__file__).resolve().parent
CRYPTO_BOT_DIR = API_DIR.parent
REPO_ROOT = CRYPTO_BOT_DIR.parent
DEFAULT_KEYS_DIR = REPO_ROOT / "revolut-keys"
DEFAULT_API_KEY_PATH = DEFAULT_KEYS_DIR / "api_key.txt"
DEFAULT_PRIVATE_KEY_PATH = DEFAULT_KEYS_DIR / "private.pem"
DEFAULT_PUBLIC_KEY_PATH = DEFAULT_KEYS_DIR / "public.pem"
MAX_SECRET_FILE_BYTES = 16 * 1024


def _env(name: str) -> str:
    return str(os.getenv(name, "")).strip()


def _resolve_secret_path(env_name: str, default_path: Path) -> Path:
    override = _env(env_name)
    if not override:
        return default_path
    return Path(override).expanduser()


def _default_candidates(default_path: Path) -> list[Path]:
    candidates = [
        default_path,
        Path.cwd() / "revolut-keys" / default_path.name,
        CRYPTO_BOT_DIR / "revolut-keys" / default_path.name,
    ]
    seen: set[Path] = set()
    output: list[Path] = []
    for candidate in candidates:
        resolved = candidate.resolve(strict=False)
        if resolved in seen:
            continue
        seen.add(resolved)
        output.append(candidate)
    return output


def _resolve_existing_secret_path(env_name: str, default_path: Path) -> Path | None:
    override = _env(env_name)
    if override:
        override_path = Path(override).expanduser()
        if override_path.exists():
            return override_path
        logger.warning(
            f"{env_name} points to missing file ({override_path}); "
            "falling back to default Revolut key locations."
        )
    for candidate in _default_candidates(default_path):
        if candidate.exists():
            return candidate
    return None


def _read_secret_file(path: Path, label: str) -> str:
    if not path.exists():
        raise RuntimeError(f"{label} file not found ({path})")
    if not path.is_file():
        raise RuntimeError(f"{label} path is not a file ({path})")
    if path.is_symlink():
        raise RuntimeError(f"{label} must not be a symlink ({path})")

    file_size = path.stat().st_size
    if file_size <= 0:
        raise RuntimeError(f"{label} file is empty ({path})")
    if file_size > MAX_SECRET_FILE_BYTES:
        raise RuntimeError(f"{label} file is unexpectedly large ({path})")

    value = path.read_text(encoding="utf-8").strip()
    if not value:
        raise RuntimeError(f"{label} file is blank ({path})")
    return value


def load_api_key(*, allow_missing: bool = False) -> tuple[str | None, str]:
    env_key = _env("REVBOT_REVOLUT_API_KEY")
    if env_key:
        return env_key, "env:REVBOT_REVOLUT_API_KEY"

    api_key_path = _resolve_existing_secret_path(
        "REVBOT_REVOLUT_API_KEY_PATH",
        DEFAULT_API_KEY_PATH,
    )
    if api_key_path is not None:
        return _read_secret_file(api_key_path, "Revolut API key"), f"file:{api_key_path}"

    if allow_missing:
        return None, "missing"

    raise RuntimeError(
        "Revolut API key is missing. "
        "Set REVBOT_REVOLUT_API_KEY or create revolut-keys/api_key.txt."
    )


def resolve_private_key_path(*, allow_missing: bool = True) -> tuple[Path | None, str]:
    private_key_path = _resolve_existing_secret_path(
        "REVBOT_REVOLUT_PRIVATE_KEY_PATH",
        DEFAULT_PRIVATE_KEY_PATH,
    )
    if private_key_path is not None:
        # Validate without exposing key material.
        _read_secret_file(private_key_path, "Revolut private key")
        return private_key_path, f"file:{private_key_path}"

    if allow_missing:
        return None, "missing"

    raise RuntimeError(
        "Revolut private key is missing. "
        "Set REVBOT_REVOLUT_PRIVATE_KEY_PATH or create revolut-keys/private.pem."
    )


def resolve_public_key_path(*, allow_missing: bool = True) -> tuple[Path | None, str]:
    public_key_path = _resolve_existing_secret_path(
        "REVBOT_REVOLUT_PUBLIC_KEY_PATH",
        DEFAULT_PUBLIC_KEY_PATH,
    )
    if public_key_path is not None:
        _read_secret_file(public_key_path, "Revolut public key")
        return public_key_path, f"file:{public_key_path}"

    if allow_missing:
        return None, "missing"

    raise RuntimeError(
        "Revolut public key is missing. "
        "Set REVBOT_REVOLUT_PUBLIC_KEY_PATH or create revolut-keys/public.pem."
    )
