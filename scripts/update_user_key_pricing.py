from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path
from typing import Any


DEFAULT_PRICING = {
    "gpt-image-2": 2,
    "gpt-image-2-2K": 2,
    "gpt-image-2-4K": 8,
}
SUPPORTED_MODELS = tuple(DEFAULT_PRICING.keys())


def normalize_pricing(value: Any) -> dict[str, int]:
    pricing = dict(DEFAULT_PRICING)
    if isinstance(value, dict):
        for model in SUPPORTED_MODELS:
            if value.get(model) is None:
                continue
            pricing[model] = max(0, int(value.get(model) or 0))
    return pricing


def overwrite_pricing(items: Any) -> tuple[list[dict[str, Any]], int]:
    if not isinstance(items, list):
        raise ValueError("user key document must be a JSON array")
    changed = 0
    updated: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            updated.append(item)
            continue
        next_item = dict(item)
        if normalize_pricing(next_item.get("pricing")) != DEFAULT_PRICING:
            changed += 1
        next_item["pricing"] = dict(DEFAULT_PRICING)
        updated.append(next_item)
    return updated, changed


def update_sqlite(db_path: Path, *, dry_run: bool) -> tuple[int, int]:
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite file not found: {db_path}")
    documents = 0
    keys_changed = 0
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT name, data FROM json_documents WHERE name LIKE 'user_keys:%'"
        ).fetchall()
        for name, data in rows:
            updated, changed = overwrite_pricing(json.loads(data))
            documents += 1
            keys_changed += changed
            if not dry_run:
                connection.execute(
                    """
                    UPDATE json_documents
                    SET data = ?, updated_at = datetime('now', 'localtime')
                    WHERE name = ?
                    """,
                    (json.dumps(updated, ensure_ascii=False), name),
                )
        if dry_run:
            connection.rollback()
    return documents, keys_changed


def update_json(json_path: Path, *, dry_run: bool) -> tuple[bool, int]:
    if not json_path.exists():
        return False, 0
    updated, changed = overwrite_pricing(json.loads(json_path.read_text(encoding="utf-8")))
    if not dry_run:
        json_path.write_text(
            json.dumps(updated, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return True, changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Overwrite all user key model pricing to 1K=2, 2K=2, 4K=8."
    )
    parser.add_argument("--sqlite", default="data/chatgpt2api.sqlite3", help="SQLite data file")
    parser.add_argument("--json", default="data/user_keys.json", help="Optional JSON backup file")
    parser.add_argument("--dry-run", action="store_true", help="Report changes without writing")
    args = parser.parse_args()

    db_documents, db_changed = update_sqlite(Path(args.sqlite), dry_run=args.dry_run)
    json_exists, json_changed = update_json(Path(args.json), dry_run=args.dry_run)
    print(
        json.dumps(
            {
                "pricing": DEFAULT_PRICING,
                "dry_run": bool(args.dry_run),
                "sqlite_documents": db_documents,
                "sqlite_keys_changed": db_changed,
                "json_updated": json_exists,
                "json_keys_changed": json_changed,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
