from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import sqlite3
import stat
import tempfile
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Callable, Iterator

from .verify import sha256_file, verify_database


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _temporary_database(destination: Path) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    os.close(descriptor)
    return Path(name)


def _database_files(path: Path) -> tuple[Path, ...]:
    return (
        path,
        Path(f"{path}-wal"),
        Path(f"{path}-shm"),
        Path(f"{path}-journal"),
    )


def _remove_database_files(path: Path) -> None:
    for candidate in _database_files(path):
        candidate.unlink(missing_ok=True)


@contextmanager
def _destination_lock(destination: Path) -> Iterator[None]:
    """Serialize recovery operations that publish into the same directory."""

    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(destination.parent, flags)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def _install_verified_database(
    destination: Path,
    populate: Callable[[Path], None],
    *,
    expected_articles: int | None,
    expected_sha256: str | None,
    overwrite: bool,
    finalize: bool,
) -> dict[str, object]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _destination_lock(destination):
        return _install_verified_database_locked(
            destination,
            populate,
            expected_articles=expected_articles,
            expected_sha256=expected_sha256,
            overwrite=overwrite,
            finalize=finalize,
        )


def _install_verified_database_locked(
    destination: Path,
    populate: Callable[[Path], None],
    *,
    expected_articles: int | None,
    expected_sha256: str | None,
    overwrite: bool,
    finalize: bool,
) -> dict[str, object]:
    if destination.is_symlink():
        raise ValueError("database destination must not be a symlink")
    destination_existed = destination.exists()
    if destination_existed and not overwrite:
        raise FileExistsError(destination)
    if destination_existed and not destination.is_file():
        raise ValueError("database destination must be a regular file")
    sidecars = [
        path
        for path in _database_files(destination)[1:]
        if path.exists() or path.is_symlink()
    ]
    if sidecars:
        raise ValueError(
            "database destination has SQLite sidecars; stop its writer and finalize it first"
        )
    temporary = _temporary_database(destination)
    rollback: Path | None = None
    installed = False
    try:
        populate(temporary)
        report = verify_database(
            temporary,
            checkpoint=finalize,
            expected_articles=expected_articles,
        )
        if not report["valid"]:
            raise RuntimeError("temporary database failed integrity or record verification")
        if expected_sha256 is not None and report["sha256"] != expected_sha256:
            raise ValueError("database SHA-256 does not match the expected snapshot")
        _fsync_file(temporary)
        if destination_existed:
            rollback = Path(f"{temporary}.rollback")
            os.link(destination, rollback, follow_symlinks=False)
            os.replace(temporary, destination)
            installed = True
        else:
            # link(2) is an atomic no-replace install. It closes the race between
            # the existence check and publication of a newly named snapshot.
            os.link(temporary, destination)
            temporary.unlink()
            installed = True
        _remove_database_files(temporary)
        _fsync_directory(destination.parent)
    except Exception:
        _remove_database_files(temporary)
        if installed and rollback is not None:
            os.replace(rollback, destination)
            _fsync_directory(destination.parent)
        elif installed:
            destination.unlink(missing_ok=True)
            _fsync_directory(destination.parent)
        elif rollback is not None:
            rollback.unlink(missing_ok=True)
        raise

    try:
        final_report = verify_database(destination, expected_articles=expected_articles)
        if not final_report["valid"]:
            raise RuntimeError("installed database failed post-replacement verification")
        if expected_sha256 is not None and final_report["sha256"] != expected_sha256:
            raise RuntimeError("installed database digest changed during replacement")
    except Exception:
        if rollback is not None:
            os.replace(rollback, destination)
        else:
            destination.unlink(missing_ok=True)
        _fsync_directory(destination.parent)
        raise
    if rollback is not None:
        rollback.unlink(missing_ok=True)
        _fsync_directory(destination.parent)
    return final_report


def backup_database(
    source: str | Path,
    destination: str | Path,
    *,
    expected_articles: int | None = None,
    overwrite: bool = False,
) -> dict[str, object]:
    """Create an atomic, finalized backup using SQLite's online backup API.

    The source is opened read-only without ``immutable=1`` so committed WAL frames
    remain visible. Only the temporary destination is checkpointed and converted
    to DELETE journal mode; the source database is never checkpointed.
    """

    source_path = Path(source)
    destination_path = Path(destination)
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if source_path.resolve() == destination_path.resolve():
        raise ValueError("backup source and destination must differ")
    source_mode = stat.S_IMODE(source_path.stat().st_mode)

    def populate(temporary: Path) -> None:
        source_uri = f"{source_path.resolve().as_uri()}?mode=ro"
        with closing(sqlite3.connect(source_uri, uri=True)) as source_connection:
            source_connection.execute("PRAGMA query_only = ON")
            source_connection.execute("PRAGMA busy_timeout = 5000")
            with closing(sqlite3.connect(temporary)) as destination_connection:
                source_connection.backup(destination_connection)
        os.chmod(temporary, source_mode)

    return _install_verified_database(
        destination_path,
        populate,
        expected_articles=expected_articles,
        expected_sha256=None,
        overwrite=overwrite,
        finalize=True,
    )


def restore_database(
    snapshot: str | Path,
    destination: str | Path,
    *,
    expected_sha256: str | None = None,
    expected_articles: int | None = None,
    overwrite: bool = False,
) -> dict[str, object]:
    """Restore a finalized snapshot through a verified atomic replacement."""

    snapshot_path = Path(snapshot)
    destination_path = Path(destination)
    if snapshot_path.is_symlink():
        raise ValueError("restore source must be a regular file, not a symlink")
    if not snapshot_path.is_file():
        raise FileNotFoundError(snapshot_path)
    if snapshot_path.resolve() == destination_path.resolve():
        raise ValueError("restore source and destination must differ")
    snapshot_mode = stat.S_IMODE(snapshot_path.stat().st_mode)

    source_report = verify_database(snapshot_path, expected_articles=expected_articles)
    if not source_report["valid"]:
        raise ValueError("restore source is not a valid finalized SQLite snapshot")
    snapshot_sha256 = str(source_report["sha256"])
    if expected_sha256 is not None and snapshot_sha256 != expected_sha256:
        raise ValueError("restore source SHA-256 does not match the expected snapshot")

    def populate(temporary: Path) -> None:
        shutil.copyfile(snapshot_path, temporary)
        if any(
            path.exists() or path.is_symlink()
            for path in _database_files(snapshot_path)[1:]
        ):
            raise ValueError("restore source gained a SQLite sidecar during copy")
        os.chmod(temporary, snapshot_mode)

    return _install_verified_database(
        destination_path,
        populate,
        expected_articles=expected_articles,
        expected_sha256=snapshot_sha256,
        overwrite=overwrite,
        finalize=False,
    )


def snapshot_sha256(path: str | Path) -> str:
    """Return the content digest used to identify an immutable database snapshot."""

    return sha256_file(Path(path))


def main() -> None:
    parser = argparse.ArgumentParser(description="Back up or restore verified SQLite snapshots")
    commands = parser.add_subparsers(dest="command", required=True)

    backup = commands.add_parser("backup", help="create an online SQLite backup")
    backup.add_argument("--source", type=Path, required=True)
    backup.add_argument("--destination", type=Path, required=True)
    backup.add_argument("--expected-articles", type=int)
    backup.add_argument("--overwrite", action="store_true")

    restore = commands.add_parser("restore", help="restore a finalized SQLite snapshot")
    restore.add_argument("--snapshot", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    restore.add_argument("--expected-sha256")
    restore.add_argument("--expected-articles", type=int)
    restore.add_argument("--overwrite", action="store_true")

    args = parser.parse_args()
    if args.expected_articles is not None and args.expected_articles < 0:
        parser.error("--expected-articles must be non-negative")
    if args.command == "backup":
        report = backup_database(
            args.source,
            args.destination,
            expected_articles=args.expected_articles,
            overwrite=args.overwrite,
        )
    else:
        if args.expected_sha256 is not None and (
            len(args.expected_sha256) != 64
            or any(character not in "0123456789abcdef" for character in args.expected_sha256)
        ):
            parser.error("--expected-sha256 must be a 64-character SHA-256 digest")
        report = restore_database(
            args.snapshot,
            args.destination,
            expected_sha256=args.expected_sha256,
            expected_articles=args.expected_articles,
            overwrite=args.overwrite,
        )
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
