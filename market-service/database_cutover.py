"""Atomic, evidence-backed migration from a legacy database into MySQL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Sequence

from persistence import Database, LATEST_SCHEMA_VERSION, utc_now


@dataclass(frozen=True)
class TableSpec:
    name: str
    columns: tuple[str, ...]
    order_by: tuple[str, ...]
    timestamp_columns: tuple[str, ...] = ()


# Parent tables precede children so foreign keys stay enabled throughout the copy.
APPLICATION_TABLES: tuple[TableSpec, ...] = (
    TableSpec(
        "companies",
        ("symbol", "name", "exchange", "sector", "industry", "region", "currency",
         "source", "metadata_json", "updated_at"),
        ("symbol",),
        ("updated_at",),
    ),
    TableSpec(
        "market_bars",
        ("symbol", "session_date", "open", "high", "low", "close", "adjusted_close",
         "volume", "source", "ingested_at"),
        ("symbol", "session_date"),
        ("ingested_at",),
    ),
    TableSpec(
        "ingestion_runs",
        ("id", "started_at", "completed_at", "status", "period", "symbols_requested",
         "bars_written", "dataset_version", "errors_json"),
        ("id",),
        ("started_at", "completed_at"),
    ),
    TableSpec(
        "model_runs",
        ("id", "symbol", "model_name", "artifact_path", "dataset_version", "training_start",
         "training_end", "training_rows", "holdout_start", "holdout_end", "holdout_rows",
         "balanced_accuracy", "roc_auc", "brier_score", "metrics_json", "baselines_json",
         "features_json", "status", "created_at"),
        ("id",),
        ("created_at",),
    ),
    TableSpec(
        "predictions",
        ("id", "symbol", "model_run_id", "model_data_date", "generated_at", "probability_up",
         "outlook", "reference_close", "expected_low", "expected_high", "actual_close",
         "actual_direction", "correct", "evaluated_at"),
        ("id",),
        ("generated_at", "evaluated_at"),
    ),
    TableSpec(
        "model_feature_baselines",
        ("model_run_id", "symbol", "feature_name", "sample_count", "mean_value", "std_value",
         "bin_edges_json", "bin_proportions_json", "created_at"),
        ("model_run_id", "feature_name"),
        ("created_at",),
    ),
    TableSpec(
        "prediction_features",
        ("prediction_id", "symbol", "model_run_id", "feature_name", "feature_value", "observed_at"),
        ("prediction_id", "feature_name"),
        ("observed_at",),
    ),
    TableSpec(
        "drift_snapshots",
        ("id", "symbol", "model_run_id", "evaluated_at", "recent_observations", "mean_psi",
         "max_psi", "status", "recommendation", "details_json"),
        ("id",),
        ("evaluated_at",),
    ),
    TableSpec(
        "document_sources",
        ("id", "symbol", "title", "document_type", "reporting_period", "source_url",
         "file_sha256", "page_count", "chunk_count", "embedding_provider", "created_at"),
        ("id",),
        ("created_at",),
    ),
    TableSpec(
        "document_chunks",
        ("id", "document_id", "symbol", "page_number", "chunk_index", "text",
         "embedding_json", "embedding_provider", "created_at"),
        ("id",),
        ("created_at",),
    ),
)


def _canonical_timestamp(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        raw_value = str(value).strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw_value)
        except ValueError:
            return raw_value
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _canonical_row(spec: TableSpec, row: Sequence[Any]) -> bytes:
    timestamp_columns = set(spec.timestamp_columns)
    values = [
        _canonical_timestamp(value) if column in timestamp_columns else value
        for column, value in zip(spec.columns, row)
    ]
    return (json.dumps(values, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")


def _select_statement(spec: TableSpec) -> str:
    return (
        f"SELECT {', '.join(spec.columns)} FROM {spec.name} "
        f"ORDER BY {', '.join(spec.order_by)}"
    )


def _digest_row_set(row_digests: list[bytes]) -> str:
    """Build an order-independent digest so database collation cannot change evidence."""
    digest = hashlib.sha256()
    for row_digest in sorted(row_digests):
        digest.update(row_digest)
    return digest.hexdigest()


def _table_evidence(connection: Any, spec: TableSpec, batch_size: int = 1000) -> Dict[str, Any]:
    cursor = connection.cursor()
    cursor.execute(_select_statement(spec))
    row_digests: list[bytes] = []
    row_count = 0
    while True:
        rows = cursor.fetchmany(batch_size)
        if not rows:
            break
        for row in rows:
            row_digests.append(hashlib.sha256(_canonical_row(spec, row)).digest())
        row_count += len(rows)
    return {"rowCount": row_count, "sha256": _digest_row_set(row_digests)}


def _application_row_counts(database: Database) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    with database.connect() as connection:
        cursor = connection.cursor()
        for spec in APPLICATION_TABLES:
            cursor.execute(f"SELECT COUNT(*) FROM {spec.name}")
            row = cursor.fetchone()
            counts[spec.name] = int(row[0]) if row else 0
    return counts


def migrate_legacy_to_mysql(
    source: Database,
    target: Database,
    *,
    confirm_empty_target: bool = False,
    batch_size: int = 1000,
    allow_legacy_target_for_tests: bool = False,
) -> Dict[str, Any]:
    """Copy existing application rows into an empty MySQL schema atomically."""
    if not confirm_empty_target:
        raise ValueError("Migration requires --confirm-empty-target.")
    if source.backend == "mysql":
        raise ValueError("Migration source must be the previous non-MySQL database.")
    if target.backend != "mysql" and not allow_legacy_target_for_tests:
        raise ValueError("Migration target must be MySQL.")
    if batch_size < 1 or batch_size > 10000:
        raise ValueError("Migration batch size must be between 1 and 10000.")
    if source.backend == "sqlite" and not source._sqlite_path().is_file():
        raise ValueError("SQLite source database does not exist.")
    if (
        source.backend == "sqlite"
        and target.backend == "sqlite"
        and source._sqlite_path() == target._sqlite_path()
    ):
        raise ValueError("Migration source and target must be different databases.")

    # The legacy database is the recovery source. Never run schema migrations
    # against it during a cutover; the copy must be read-only on that side.
    target.initialize_schema()
    populated_tables = {
        table: count for table, count in _application_row_counts(target).items() if count > 0
    }
    if populated_tables:
        raise ValueError("Migration target contains project data and will not be overwritten.")

    table_results: Dict[str, Dict[str, Any]] = {}
    with source.connect() as source_connection, target.connect() as target_connection:
        # The first read establishes a stable source snapshot; all target writes
        # share one transaction until row-count and checksum verification passes.
        if source.backend == "sqlite":
            source_connection.execute("BEGIN")
        elif source.backend == "postgresql":
            source_connection.execute(
                "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
            )
        for spec in APPLICATION_TABLES:
            source_cursor = source_connection.cursor()
            source_cursor.execute(_select_statement(spec))
            target_cursor = target_connection.cursor()
            placeholders = ", ".join("?" for _ in spec.columns)
            insert = target._sql(
                f"INSERT INTO {spec.name} ({', '.join(spec.columns)}) VALUES ({placeholders})"
            )
            source_row_digests: list[bytes] = []
            source_count = 0
            while True:
                rows = source_cursor.fetchmany(batch_size)
                if not rows:
                    break
                materialized_rows = [tuple(row) for row in rows]
                target_cursor.executemany(insert, materialized_rows)
                for row in materialized_rows:
                    source_row_digests.append(hashlib.sha256(_canonical_row(spec, row)).digest())
                source_count += len(materialized_rows)

            target_evidence = _table_evidence(target_connection, spec, batch_size)
            source_sha256 = _digest_row_set(source_row_digests)
            if (
                source_count != target_evidence["rowCount"]
                or source_sha256 != target_evidence["sha256"]
            ):
                raise RuntimeError(f"Migration verification failed for allowlisted table {spec.name}.")
            table_results[spec.name] = {
                "rowCount": source_count,
                "sha256": source_sha256,
                "verified": True,
            }

    total_rows = sum(result["rowCount"] for result in table_results.values())
    return {
        "status": "verified",
        "sourceBackend": source.backend,
        "targetBackend": target.backend,
        "schemaVersion": LATEST_SCHEMA_VERSION,
        "tablesVerified": len(table_results),
        "totalRows": total_rows,
        "tables": table_results,
        "credentialsIncluded": False,
        "completedAt": utc_now(),
    }


def write_cutover_manifest(manifest: Dict[str, Any], path: Path) -> Path:
    output = Path(path).resolve()
    if output.exists():
        raise ValueError("Migration manifest already exists; choose a new path.")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return output
