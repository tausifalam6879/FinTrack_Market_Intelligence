"""Safe database status, logical backup verification and empty-target restore tools."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, unquote, urlparse

from persistence import Database, utc_now


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _postgres_environment(database_url: str) -> tuple[Dict[str, str], list[str]]:
    parsed = urlparse(database_url.replace("postgres://", "postgresql://", 1))
    if not parsed.hostname or not parsed.path.strip("/") or not parsed.username:
        raise ValueError("DATABASE_URL is not a complete PostgreSQL connection string.")
    environment = os.environ.copy()
    if parsed.password:
        environment["PGPASSWORD"] = unquote(parsed.password)
    query = parse_qs(parsed.query)
    if query.get("sslmode"):
        environment["PGSSLMODE"] = query["sslmode"][0]
    connection_arguments = [
        "--host", parsed.hostname,
        "--port", str(parsed.port or 5432),
        "--username", unquote(parsed.username),
        "--dbname", unquote(parsed.path.strip("/")),
    ]
    return environment, connection_arguments


def database_status(database: Optional[Database] = None) -> Dict[str, Any]:
    repository = database or Database()
    repository.initialize_schema()
    repository.ping()
    schema = repository.schema_status()
    return {
        "status": "ready" if schema["upToDate"] else "migration_required",
        "backend": repository.backend,
        "location": repository.location,
        "durableAcrossDeploys": repository.backend == "postgresql",
        "schema": schema,
        "backupPolicy": os.getenv("DATABASE_BACKUP_POLICY", "not_configured"),
        "checkedAt": utc_now(),
    }


def create_backup(target: Path, database: Optional[Database] = None) -> Dict[str, Any]:
    repository = database or Database()
    repository.initialize_schema()
    target = Path(target).resolve()
    if target.exists():
        raise ValueError("Backup target already exists; choose a new timestamped file.")
    target.parent.mkdir(parents=True, exist_ok=True)

    if repository.backend == "sqlite":
        source = sqlite3.connect(repository._sqlite_path())
        destination = sqlite3.connect(target)
        try:
            source.backup(destination)
        finally:
            destination.close()
            source.close()
        backup_format = "sqlite-online-backup"
    else:
        executable = shutil.which("pg_dump")
        if not executable:
            raise RuntimeError("pg_dump is required for PostgreSQL logical backups.")
        environment, connection = _postgres_environment(repository.url)
        subprocess.run([
            executable,
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file", str(target),
            *connection,
        ], env=environment, check=True)
        backup_format = "postgresql-custom"

    manifest = {
        "backupFile": target.name,
        "backend": repository.backend,
        "format": backup_format,
        "sha256": _sha256(target),
        "sizeBytes": target.stat().st_size,
        "schema": repository.schema_status(),
        "createdAt": utc_now(),
        "containsCredentials": False,
    }
    manifest_path = target.with_suffix(target.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return {**manifest, "path": str(target), "manifestPath": str(manifest_path)}


def verify_backup(path: Path) -> Dict[str, Any]:
    backup_path = Path(path).resolve()
    manifest_path = backup_path.with_suffix(backup_path.suffix + ".manifest.json")
    if not backup_path.is_file() or not manifest_path.is_file():
        raise ValueError("Backup file and its manifest are both required.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    actual = _sha256(backup_path)
    verified = actual == manifest.get("sha256") and backup_path.stat().st_size > 0
    if not verified:
        raise ValueError("Backup checksum verification failed.")
    return {
        "status": "verified",
        "backend": manifest.get("backend"),
        "format": manifest.get("format"),
        "sha256": actual,
        "sizeBytes": backup_path.stat().st_size,
        "verifiedAt": utc_now(),
    }


def restore_empty_target(
    backup_path: Path,
    database: Optional[Database] = None,
    confirm_empty_target: bool = False,
) -> Dict[str, Any]:
    if not confirm_empty_target:
        raise ValueError("Restore requires --confirm-empty-target.")
    verification = verify_backup(backup_path)
    repository = database or Database()
    if repository.user_table_count() != 0:
        raise ValueError("Restore target is not empty; existing project tables will not be overwritten.")

    source = Path(backup_path).resolve()
    if repository.backend == "sqlite":
        if verification["format"] != "sqlite-online-backup":
            raise ValueError("A SQLite target requires a SQLite online-backup file.")
        shutil.copy2(source, repository._sqlite_path())
    else:
        if verification["format"] != "postgresql-custom":
            raise ValueError("A PostgreSQL target requires a PostgreSQL custom-format dump.")
        executable = shutil.which("pg_restore")
        if not executable:
            raise RuntimeError("pg_restore is required for PostgreSQL restores.")
        environment, connection = _postgres_environment(repository.url)
        subprocess.run([
            executable,
            "--exit-on-error",
            "--no-owner",
            "--no-privileges",
            *connection,
            str(source),
        ], env=environment, check=True)

    repository.ping()
    return {
        "status": "restored",
        "backend": repository.backend,
        "schema": repository.schema_status(),
        "restoredAt": utc_now(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="FinTrack database maintenance without credential output.")
    parser.add_argument("command", choices=["status", "backup", "verify", "restore"])
    parser.add_argument("path", nargs="?")
    parser.add_argument("--database-url")
    parser.add_argument("--confirm-empty-target", action="store_true")
    arguments = parser.parse_args()
    database = Database(arguments.database_url)
    if arguments.command == "status":
        result = database_status(database)
    elif arguments.command == "backup":
        if not arguments.path:
            raise SystemExit("backup requires a new output path")
        result = create_backup(Path(arguments.path), database)
    elif arguments.command == "verify":
        if not arguments.path:
            raise SystemExit("verify requires a backup path")
        result = verify_backup(Path(arguments.path))
    else:
        if not arguments.path:
            raise SystemExit("restore requires a backup path")
        result = restore_empty_target(
            Path(arguments.path), database, arguments.confirm_empty_target
        )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
