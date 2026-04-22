from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
CRYPTO_BOT = REPO_ROOT / "crypto_bot"
OUTPUT = REPO_ROOT / "docs" / "precision_inventory.json"

SKIP_DIR_PREFIXES = ("pytest-cache-files-", "__pycache__")
SKIP_DIR_NAMES = {
    "state/backups",
    "state/launcher_logs",
    "state/pytest_runtime",
    "state/pytest_base_env",
}


def _should_skip_dir(relative: Path) -> bool:
    rel = relative.as_posix()
    if rel in SKIP_DIR_NAMES:
        return True
    parts = relative.parts
    return any(part.startswith(SKIP_DIR_PREFIXES) for part in parts)


def _category(relative: Path) -> str:
    return relative.parts[0] if relative.parts else "."


def build_inventory() -> dict:
    rows: list[dict] = []
    for path in CRYPTO_BOT.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(CRYPTO_BOT)
        parent = rel.parent
        if _should_skip_dir(parent):
            continue
        try:
            line_count = 0
            if path.suffix.lower() in {".py", ".md", ".json", ".yaml", ".yml", ".txt", ".ps1"}:
                with path.open("r", encoding="utf-8", errors="ignore") as handle:
                    line_count = sum(1 for _ in handle)
            stat = path.stat()
        except OSError:
            continue

        rows.append(
            {
                "path": rel.as_posix(),
                "category": _category(rel),
                "suffix": path.suffix.lower(),
                "bytes": int(stat.st_size),
                "lines": int(line_count),
                "modified_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            }
        )

    rows.sort(key=lambda row: row["path"])
    by_category: dict[str, int] = {}
    for row in rows:
        key = row["category"]
        by_category[key] = by_category.get(key, 0) + 1

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "root": str(CRYPTO_BOT),
        "file_count": len(rows),
        "categories": dict(sorted(by_category.items(), key=lambda item: item[0])),
        "files": rows,
    }


def main() -> int:
    payload = build_inventory()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(OUTPUT),
                "file_count": payload.get("file_count"),
                "categories": payload.get("categories"),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

