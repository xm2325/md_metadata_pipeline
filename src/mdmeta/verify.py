from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from .storage import SCHEMA_VERSION, SQLiteRecordStore


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_database(
    database_path: str | Path,
    *,
    checkpoint: bool = False,
    expected_articles: int | None = None,
) -> dict[str, object]:
    path = Path(database_path)
    if not path.is_file():
        raise FileNotFoundError(path)
    store = SQLiteRecordStore(path, read_only=not checkpoint)
    checkpoint_result = store.checkpoint() if checkpoint else None
    integrity = store.integrity_report()
    article_count = store.count_articles()
    wal_path = Path(f"{path}-wal")
    wal_bytes = wal_path.stat().st_size if wal_path.exists() else 0
    checkpoint_complete = checkpoint_result is None or (
        checkpoint_result[0] == 0 and checkpoint_result[1] == checkpoint_result[2]
    )
    valid = (
        integrity["integrity"] == ["ok"]
        and integrity["foreign_key_violations"] == []
        and integrity["schema_version"] == SCHEMA_VERSION
        and integrity["journal_mode"] == "delete"
        and checkpoint_complete
        and wal_bytes == 0
        and (expected_articles is None or article_count == expected_articles)
    )
    return {
        "database": path.name,
        "byte_size": path.stat().st_size,
        "sha256": _sha256(path),
        "article_count": article_count,
        "expected_article_count": expected_articles,
        "checkpoint": list(checkpoint_result) if checkpoint_result is not None else None,
        "checkpoint_complete": checkpoint_complete,
        "wal_byte_size": wal_bytes,
        "integrity": integrity,
        "valid": valid,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify a SQLite snapshot and emit a machine-readable integrity manifest."
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument(
        "--checkpoint",
        action="store_true",
        help="checkpoint and truncate the WAL before hashing a writable snapshot",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--expected-articles",
        type=int,
        help="require this exact article count before accepting the snapshot",
    )
    args = parser.parse_args()

    if args.expected_articles is not None and args.expected_articles < 0:
        parser.error("--expected-articles must be non-negative")
    report = verify_database(
        args.database,
        checkpoint=args.checkpoint,
        expected_articles=args.expected_articles,
    )
    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    if not report["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
