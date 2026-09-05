"""Persistent market-data storage with MySQL as the primary application database."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Full, LifoQueue
import sqlite3
import ssl
from threading import Lock
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence
from urllib.parse import parse_qs, quote, unquote, urlparse


LATEST_SCHEMA_VERSION = 5
_MYSQL_POOLS: Dict[str, LifoQueue[Any]] = {}
_MYSQL_POOLS_LOCK = Lock()


def _mysql_pool(database_url: str) -> LifoQueue[Any]:
    """Return a small process-local pool without retaining a plaintext URL key."""
    key = hashlib.sha256(database_url.encode("utf-8")).hexdigest()
    try:
        configured_size = int(os.getenv("MYSQL_POOL_SIZE", "8"))
    except ValueError:
        configured_size = 8
    pool_size = max(1, min(configured_size, 32))
    with _MYSQL_POOLS_LOCK:
        pool = _MYSQL_POOLS.get(key)
        if pool is None:
            pool = LifoQueue(maxsize=pool_size)
            _MYSQL_POOLS[key] = pool
        return pool


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def mysql_url_from_environment() -> str:
    """Build a URL without requiring credentials to be written into project files."""
    host = os.getenv("MYSQL_HOST", "127.0.0.1").strip() or "127.0.0.1"
    port = os.getenv("MYSQL_PORT", "3306").strip() or "3306"
    user = quote(os.getenv("MYSQL_USER", "fintrack").strip() or "fintrack", safe="")
    password = quote(os.getenv("MYSQL_PASSWORD", "fintrack_local_only"), safe="")
    database_name = quote(os.getenv("MYSQL_DATABASE", "fintrack").strip() or "fintrack", safe="")
    return f"mysql://{user}:{password}@{host}:{port}/{database_name}"


class Database:
    """Small DB-API repository with a production-ready MySQL path.

    The older adapters remain temporarily readable so existing data can be
    migrated safely before they are removed. New local and hosted setups use
    MySQL.
    """

    def __init__(self, url: Optional[str] = None):
        self.url = str(url or os.getenv("DATABASE_URL") or mysql_url_from_environment())
        if self.url.startswith(("mysql://", "mysql+pymysql://")):
            self.backend = "mysql"
        elif self.url.startswith(("postgresql://", "postgres://")):
            self.backend = "postgresql"
        elif self.url.startswith("sqlite:///"):
            self.backend = "sqlite"
        else:
            raise ValueError(
                "DATABASE_URL must use mysql://. Legacy postgresql:// and sqlite:/// URLs "
                "are accepted only for verified migration and compatibility tests."
            )

    @property
    def location(self) -> str:
        if self.backend in {"mysql", "postgresql"}:
            return "DATABASE_URL"
        return str(self._sqlite_path())

    def _mysql_connection_options(self) -> Dict[str, Any]:
        normalized = self.url.replace("mysql+pymysql://", "mysql://", 1)
        parsed = urlparse(normalized)
        database_name = unquote(parsed.path.lstrip("/"))
        if not parsed.hostname or not parsed.username or not database_name:
            raise ValueError(
                "MySQL DATABASE_URL must include user, host and database name: "
                "mysql://USER:PASSWORD@HOST:3306/DATABASE"
            )
        query = parse_qs(parsed.query)
        options: Dict[str, Any] = {
            "host": parsed.hostname,
            "port": parsed.port or 3306,
            "user": unquote(parsed.username),
            "password": unquote(parsed.password or ""),
            "database": database_name,
            "charset": query.get("charset", ["utf8mb4"])[0],
            "connect_timeout": int(query.get("connect_timeout", ["10"])[0]),
            "read_timeout": int(query.get("read_timeout", ["30"])[0]),
            "write_timeout": int(query.get("write_timeout", ["30"])[0]),
            "autocommit": False,
        }
        ssl_mode = query.get("ssl-mode", query.get("sslmode", [""]))[0].lower()
        ssl_enabled = query.get("ssl", [""])[0].lower() in {"1", "true", "yes", "required"}
        if ssl_enabled or ssl_mode in {"required", "verify_ca", "verify_identity"}:
            # An empty dict is falsey and lets PyMySQL treat TLS as optional.
            # Require encrypted, verified transport for hosted connections.
            context = ssl.create_default_context(cafile=query.get("ssl-ca", [None])[0])
            context.check_hostname = ssl_mode != "verify_ca"
            options["ssl"] = context
        return options

    def _sqlite_path(self) -> Path:
        prefix = "sqlite:///"
        raw_path = self.url[len(prefix):] if self.url.startswith(prefix) else self.url
        path = Path(raw_path).expanduser()
        return path if path.is_absolute() else (Path.cwd() / path).resolve()

    @contextmanager
    def connect(self) -> Iterator[Any]:
        pool: Optional[LifoQueue[Any]] = None
        if self.backend == "mysql":
            try:
                import pymysql
            except ImportError as error:
                raise RuntimeError(
                    "MySQL requires PyMySQL. Install market-service/requirements-runtime.txt first."
                ) from error
            pool = _mysql_pool(self.url)
            connection = None
            while connection is None:
                try:
                    candidate = pool.get_nowait()
                except Empty:
                    connection = pymysql.connect(**self._mysql_connection_options())
                    break
                try:
                    candidate.ping(reconnect=False)
                    connection = candidate
                except Exception:
                    candidate.close()
        elif self.backend == "postgresql":
            try:
                import psycopg
            except ImportError as error:
                raise RuntimeError(
                    "PostgreSQL requires psycopg. Install market-service/requirements.txt first."
                ) from error
            connection = psycopg.connect(self.url)
        else:
            path = self._sqlite_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(path)
            connection.execute("PRAGMA foreign_keys = ON")

        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            if pool is not None and getattr(connection, "open", False):
                try:
                    pool.put_nowait(connection)
                except Full:
                    connection.close()
            else:
                connection.close()

    def _sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self.backend in {"mysql", "postgresql"} else statement

    def ping(self) -> None:
        """Verify that the configured database accepts a minimal read query."""
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT 1")
            row = cursor.fetchone()
            if not row or int(row[0]) != 1:
                raise RuntimeError("Database readiness query returned an unexpected result.")

    @staticmethod
    def _rows(cursor: Any) -> List[Dict[str, Any]]:
        description = cursor.description or []
        columns = [column.name if hasattr(column, "name") else column[0] for column in description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    @staticmethod
    def _mysql_schema_statements() -> List[str]:
        """Return MySQL 8 schema statements in migration-version order."""
        table_options = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
        return [
            """
            CREATE TABLE IF NOT EXISTS companies (
                symbol VARCHAR(32) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                exchange VARCHAR(64),
                sector VARCHAR(191),
                industry VARCHAR(191),
                region VARCHAR(64),
                currency VARCHAR(16),
                source VARCHAR(191) NOT NULL,
                metadata_json LONGTEXT NOT NULL,
                updated_at VARCHAR(40) NOT NULL
            )
            """ + table_options,
            """
            CREATE TABLE IF NOT EXISTS market_bars (
                symbol VARCHAR(32) NOT NULL,
                session_date VARCHAR(10) NOT NULL,
                open DOUBLE NOT NULL,
                high DOUBLE NOT NULL,
                low DOUBLE NOT NULL,
                close DOUBLE NOT NULL,
                adjusted_close DOUBLE,
                volume DOUBLE NOT NULL,
                source VARCHAR(191) NOT NULL,
                ingested_at VARCHAR(40) NOT NULL,
                PRIMARY KEY (symbol, session_date)
            )
            """ + table_options,
            """
            CREATE TABLE IF NOT EXISTS ingestion_runs (
                id VARCHAR(64) PRIMARY KEY,
                started_at VARCHAR(40) NOT NULL,
                completed_at VARCHAR(40),
                status VARCHAR(32) NOT NULL,
                period VARCHAR(32) NOT NULL,
                symbols_requested INT NOT NULL,
                bars_written INT NOT NULL DEFAULT 0,
                dataset_version VARCHAR(128),
                errors_json LONGTEXT NOT NULL
            )
            """ + table_options,
            """
            CREATE TABLE IF NOT EXISTS model_runs (
                id VARCHAR(64) PRIMARY KEY,
                symbol VARCHAR(32) NOT NULL,
                model_name VARCHAR(191) NOT NULL,
                artifact_path TEXT NOT NULL,
                dataset_version VARCHAR(128) NOT NULL,
                training_start VARCHAR(10) NOT NULL,
                training_end VARCHAR(10) NOT NULL,
                training_rows INT NOT NULL,
                holdout_start VARCHAR(10) NOT NULL,
                holdout_end VARCHAR(10) NOT NULL,
                holdout_rows INT NOT NULL,
                balanced_accuracy DOUBLE NOT NULL,
                roc_auc DOUBLE,
                brier_score DOUBLE NOT NULL,
                metrics_json LONGTEXT NOT NULL,
                baselines_json LONGTEXT NOT NULL,
                features_json LONGTEXT NOT NULL,
                status VARCHAR(32) NOT NULL,
                created_at VARCHAR(40) NOT NULL
            )
            """ + table_options,
            """
            CREATE TABLE IF NOT EXISTS predictions (
                id VARCHAR(96) PRIMARY KEY,
                symbol VARCHAR(32) NOT NULL,
                model_run_id VARCHAR(64),
                model_data_date VARCHAR(10) NOT NULL,
                generated_at VARCHAR(40) NOT NULL,
                probability_up DOUBLE NOT NULL,
                outlook VARCHAR(24) NOT NULL,
                reference_close DOUBLE NOT NULL,
                expected_low DOUBLE,
                expected_high DOUBLE,
                actual_close DOUBLE,
                actual_direction VARCHAR(16),
                correct TINYINT,
                evaluated_at VARCHAR(40)
            )
            """ + table_options,
            """
            CREATE TABLE IF NOT EXISTS model_feature_baselines (
                model_run_id VARCHAR(64) NOT NULL,
                symbol VARCHAR(32) NOT NULL,
                feature_name VARCHAR(128) NOT NULL,
                sample_count INT NOT NULL,
                mean_value DOUBLE NOT NULL,
                std_value DOUBLE NOT NULL,
                bin_edges_json LONGTEXT NOT NULL,
                bin_proportions_json LONGTEXT NOT NULL,
                created_at VARCHAR(40) NOT NULL,
                PRIMARY KEY (model_run_id, feature_name)
            )
            """ + table_options,
            """
            CREATE TABLE IF NOT EXISTS prediction_features (
                prediction_id VARCHAR(96) NOT NULL,
                symbol VARCHAR(32) NOT NULL,
                model_run_id VARCHAR(64) NOT NULL,
                feature_name VARCHAR(128) NOT NULL,
                feature_value DOUBLE NOT NULL,
                observed_at VARCHAR(40) NOT NULL,
                PRIMARY KEY (prediction_id, feature_name),
                CONSTRAINT fk_prediction_features_prediction
                    FOREIGN KEY (prediction_id) REFERENCES predictions(id) ON DELETE CASCADE
            )
            """ + table_options,
            """
            CREATE TABLE IF NOT EXISTS drift_snapshots (
                id VARCHAR(96) PRIMARY KEY,
                symbol VARCHAR(32) NOT NULL,
                model_run_id VARCHAR(64) NOT NULL,
                evaluated_at VARCHAR(40) NOT NULL,
                recent_observations INT NOT NULL,
                mean_psi DOUBLE,
                max_psi DOUBLE,
                status VARCHAR(32) NOT NULL,
                recommendation VARCHAR(64) NOT NULL,
                details_json LONGTEXT NOT NULL
            )
            """ + table_options,
            """
            CREATE TABLE IF NOT EXISTS document_sources (
                id VARCHAR(96) PRIMARY KEY,
                symbol VARCHAR(32) NOT NULL,
                title VARCHAR(512) NOT NULL,
                document_type VARCHAR(64) NOT NULL,
                reporting_period VARCHAR(64),
                source_url TEXT,
                file_sha256 VARCHAR(64) NOT NULL,
                page_count INT NOT NULL,
                chunk_count INT NOT NULL,
                embedding_provider VARCHAR(64) NOT NULL,
                created_at VARCHAR(40) NOT NULL
            )
            """ + table_options,
            """
            CREATE TABLE IF NOT EXISTS document_chunks (
                id VARCHAR(96) PRIMARY KEY,
                document_id VARCHAR(96) NOT NULL,
                symbol VARCHAR(32) NOT NULL,
                page_number INT NOT NULL,
                chunk_index INT NOT NULL,
                text LONGTEXT NOT NULL,
                embedding_json LONGTEXT NOT NULL,
                embedding_provider VARCHAR(64) NOT NULL,
                created_at VARCHAR(40) NOT NULL,
                CONSTRAINT fk_document_chunks_source
                    FOREIGN KEY (document_id) REFERENCES document_sources(id) ON DELETE CASCADE
            )
            """ + table_options,
            "CREATE INDEX idx_market_bars_symbol_date ON market_bars(symbol, session_date)",
            "CREATE INDEX idx_model_runs_symbol_created ON model_runs(symbol, created_at)",
            "CREATE INDEX idx_predictions_symbol_date ON predictions(symbol, model_data_date)",
            "CREATE INDEX idx_prediction_features_model ON prediction_features(symbol, model_run_id, observed_at)",
            "CREATE INDEX idx_drift_snapshots_symbol ON drift_snapshots(symbol, evaluated_at)",
            "CREATE INDEX idx_document_sources_symbol ON document_sources(symbol, created_at)",
            "CREATE INDEX idx_document_chunks_symbol ON document_chunks(symbol, embedding_provider)",
            "ALTER TABLE document_sources MODIFY reporting_period VARCHAR(64)",
        ]

    def _initialize_mysql_schema(self) -> None:
        statements = self._mysql_schema_statements()
        migrations = [
            (1, "core-market-and-model-registry", statements[:5]),
            (2, "prediction-feature-and-drift-monitoring", statements[5:8]),
            (3, "document-rag-storage", statements[8:10]),
            (4, "query-performance-indexes", statements[10:17]),
            (5, "document-reporting-period-capacity", statements[17:]),
        ]
        migration_table = """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INT PRIMARY KEY,
                name VARCHAR(191) NOT NULL,
                applied_at VARCHAR(40) NOT NULL
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(migration_table)
            cursor.execute("SELECT version FROM schema_migrations")
            applied = {int(row[0]) for row in cursor.fetchall()}
            for version, name, migration_statements in migrations:
                if version in applied:
                    continue
                for statement in migration_statements:
                    try:
                        cursor.execute(statement)
                    except Exception as error:
                        # MySQL error 1061 means an index from an interrupted
                        # migration already exists. Continuing is idempotent.
                        if version != 4 or not error.args or int(error.args[0]) != 1061:
                            raise
                cursor.execute(
                    "INSERT IGNORE INTO schema_migrations (version, name, applied_at) VALUES (%s, %s, %s)",
                    (version, name, utc_now()),
                )

    def initialize_schema(self) -> None:
        if self.backend == "mysql":
            self._initialize_mysql_schema()
            return
        timestamp_type = "TIMESTAMPTZ" if self.backend == "postgresql" else "TEXT"
        statements = [
            f"""
            CREATE TABLE IF NOT EXISTS companies (
                symbol TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                exchange TEXT,
                sector TEXT,
                industry TEXT,
                region TEXT,
                currency TEXT,
                source TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{{}}',
                updated_at {timestamp_type} NOT NULL
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS market_bars (
                symbol TEXT NOT NULL,
                session_date TEXT NOT NULL,
                open DOUBLE PRECISION NOT NULL,
                high DOUBLE PRECISION NOT NULL,
                low DOUBLE PRECISION NOT NULL,
                close DOUBLE PRECISION NOT NULL,
                adjusted_close DOUBLE PRECISION,
                volume DOUBLE PRECISION NOT NULL,
                source TEXT NOT NULL,
                ingested_at {timestamp_type} NOT NULL,
                PRIMARY KEY (symbol, session_date)
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS ingestion_runs (
                id TEXT PRIMARY KEY,
                started_at {timestamp_type} NOT NULL,
                completed_at {timestamp_type},
                status TEXT NOT NULL,
                period TEXT NOT NULL,
                symbols_requested INTEGER NOT NULL,
                bars_written INTEGER NOT NULL DEFAULT 0,
                dataset_version TEXT,
                errors_json TEXT NOT NULL DEFAULT '[]'
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS model_runs (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                model_name TEXT NOT NULL,
                artifact_path TEXT NOT NULL,
                dataset_version TEXT NOT NULL,
                training_start TEXT NOT NULL,
                training_end TEXT NOT NULL,
                training_rows INTEGER NOT NULL,
                holdout_start TEXT NOT NULL,
                holdout_end TEXT NOT NULL,
                holdout_rows INTEGER NOT NULL,
                balanced_accuracy DOUBLE PRECISION NOT NULL,
                roc_auc DOUBLE PRECISION,
                brier_score DOUBLE PRECISION NOT NULL,
                metrics_json TEXT NOT NULL,
                baselines_json TEXT NOT NULL,
                features_json TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at {timestamp_type} NOT NULL
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS predictions (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                model_run_id TEXT,
                model_data_date TEXT NOT NULL,
                generated_at {timestamp_type} NOT NULL,
                probability_up DOUBLE PRECISION NOT NULL,
                outlook TEXT NOT NULL,
                reference_close DOUBLE PRECISION NOT NULL,
                expected_low DOUBLE PRECISION,
                expected_high DOUBLE PRECISION,
                actual_close DOUBLE PRECISION,
                actual_direction TEXT,
                correct INTEGER,
                evaluated_at {timestamp_type}
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS model_feature_baselines (
                model_run_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                feature_name TEXT NOT NULL,
                sample_count INTEGER NOT NULL,
                mean_value DOUBLE PRECISION NOT NULL,
                std_value DOUBLE PRECISION NOT NULL,
                bin_edges_json TEXT NOT NULL,
                bin_proportions_json TEXT NOT NULL,
                created_at {timestamp_type} NOT NULL,
                PRIMARY KEY (model_run_id, feature_name)
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS prediction_features (
                prediction_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                model_run_id TEXT NOT NULL,
                feature_name TEXT NOT NULL,
                feature_value DOUBLE PRECISION NOT NULL,
                observed_at {timestamp_type} NOT NULL,
                PRIMARY KEY (prediction_id, feature_name),
                FOREIGN KEY (prediction_id) REFERENCES predictions(id) ON DELETE CASCADE
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS drift_snapshots (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                model_run_id TEXT NOT NULL,
                evaluated_at {timestamp_type} NOT NULL,
                recent_observations INTEGER NOT NULL,
                mean_psi DOUBLE PRECISION,
                max_psi DOUBLE PRECISION,
                status TEXT NOT NULL,
                recommendation TEXT NOT NULL,
                details_json TEXT NOT NULL
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS document_sources (
                id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                title TEXT NOT NULL,
                document_type TEXT NOT NULL,
                reporting_period TEXT,
                source_url TEXT,
                file_sha256 TEXT NOT NULL,
                page_count INTEGER NOT NULL,
                chunk_count INTEGER NOT NULL,
                embedding_provider TEXT NOT NULL,
                created_at {timestamp_type} NOT NULL
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                symbol TEXT NOT NULL,
                page_number INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                text TEXT NOT NULL,
                embedding_json TEXT NOT NULL,
                embedding_provider TEXT NOT NULL,
                created_at {timestamp_type} NOT NULL,
                FOREIGN KEY (document_id) REFERENCES document_sources(id) ON DELETE CASCADE
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_market_bars_symbol_date ON market_bars(symbol, session_date)",
            "CREATE INDEX IF NOT EXISTS idx_model_runs_symbol_created ON model_runs(symbol, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_predictions_symbol_date ON predictions(symbol, model_data_date)",
            "CREATE INDEX IF NOT EXISTS idx_prediction_features_model ON prediction_features(symbol, model_run_id, observed_at)",
            "CREATE INDEX IF NOT EXISTS idx_drift_snapshots_symbol ON drift_snapshots(symbol, evaluated_at)",
            "CREATE INDEX IF NOT EXISTS idx_document_sources_symbol ON document_sources(symbol, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_document_chunks_symbol ON document_chunks(symbol, embedding_provider)",
        ]
        migrations = [
            (1, "core-market-and-model-registry", statements[:5]),
            (2, "prediction-feature-and-drift-monitoring", statements[5:8]),
            (3, "document-rag-storage", statements[8:10]),
            (4, "query-performance-indexes", statements[10:]),
            (5, "document-reporting-period-capacity", []),
        ]
        migration_table = f"""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at {timestamp_type} NOT NULL
            )
        """
        select_versions = "SELECT version FROM schema_migrations"
        record_migration = self._sql("""
            INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)
            ON CONFLICT(version) DO NOTHING
        """)
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(migration_table)
            cursor.execute(select_versions)
            applied = {int(row[0]) for row in cursor.fetchall()}
            for version, name, migration_statements in migrations:
                if version in applied:
                    continue
                for statement in migration_statements:
                    cursor.execute(statement)
                cursor.execute(record_migration, (version, name, utc_now()))

    def schema_status(self) -> Dict[str, Any]:
        statement = """
            SELECT version, name, applied_at FROM schema_migrations ORDER BY version ASC
        """
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(statement)
            migrations = self._rows(cursor)
        current = max((int(row["version"]) for row in migrations), default=0)
        return {
            "currentVersion": current,
            "expectedVersion": LATEST_SCHEMA_VERSION,
            "upToDate": current == LATEST_SCHEMA_VERSION,
            "appliedMigrations": [{
                "version": int(row["version"]),
                "name": row["name"],
                "appliedAt": str(row["applied_at"]),
            } for row in migrations],
        }

    def user_table_count(self) -> int:
        if self.backend == "mysql":
            statement = """
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = DATABASE() AND table_type = 'BASE TABLE'
            """
        elif self.backend == "postgresql":
            statement = """
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            """
        else:
            statement = """
                SELECT COUNT(*) FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
            """
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(statement)
            row = cursor.fetchone()
            return int(row[0]) if row else 0

    def upsert_company(self, company: Dict[str, Any]) -> None:
        if self.backend == "mysql":
            statement = """
                INSERT INTO companies (
                    symbol, name, exchange, sector, industry, region, currency,
                    source, metadata_json, updated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    exchange = VALUES(exchange),
                    sector = VALUES(sector),
                    industry = VALUES(industry),
                    region = VALUES(region),
                    currency = VALUES(currency),
                    source = VALUES(source),
                    metadata_json = VALUES(metadata_json),
                    updated_at = VALUES(updated_at)
            """
        else:
            statement = self._sql("""
                INSERT INTO companies (
                    symbol, name, exchange, sector, industry, region, currency,
                    source, metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    name = excluded.name,
                    exchange = excluded.exchange,
                    sector = excluded.sector,
                    industry = excluded.industry,
                    region = excluded.region,
                    currency = excluded.currency,
                    source = excluded.source,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
            """)
        values = (
            company["symbol"], company.get("name") or company["symbol"], company.get("exchange"),
            company.get("sector"), company.get("industry"), company.get("region"),
            company.get("currency"), company.get("source") or "Yahoo Finance",
            json.dumps(company.get("metadata") or {}, sort_keys=True), utc_now(),
        )
        with self.connect() as connection:
            connection.cursor().execute(statement, values)

    def upsert_market_bars(self, bars: Iterable[Dict[str, Any]]) -> int:
        rows = list(bars)
        if not rows:
            return 0
        if self.backend == "mysql":
            statement = """
                INSERT INTO market_bars (
                    symbol, session_date, open, high, low, close, adjusted_close,
                    volume, source, ingested_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    open = VALUES(open),
                    high = VALUES(high),
                    low = VALUES(low),
                    close = VALUES(close),
                    adjusted_close = VALUES(adjusted_close),
                    volume = VALUES(volume),
                    source = VALUES(source),
                    ingested_at = VALUES(ingested_at)
            """
        else:
            statement = self._sql("""
                INSERT INTO market_bars (
                    symbol, session_date, open, high, low, close, adjusted_close,
                    volume, source, ingested_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol, session_date) DO UPDATE SET
                    open = excluded.open,
                    high = excluded.high,
                    low = excluded.low,
                    close = excluded.close,
                    adjusted_close = excluded.adjusted_close,
                    volume = excluded.volume,
                    source = excluded.source,
                    ingested_at = excluded.ingested_at
            """)
        values = [(
            row["symbol"], row["session_date"], row["open"], row["high"], row["low"],
            row["close"], row.get("adjusted_close"), row["volume"],
            row.get("source") or "Yahoo Finance", row.get("ingested_at") or utc_now(),
        ) for row in rows]
        with self.connect() as connection:
            connection.cursor().executemany(statement, values)
        return len(values)

    def create_ingestion_run(self, run: Dict[str, Any]) -> None:
        statement = self._sql("""
            INSERT INTO ingestion_runs (
                id, started_at, status, period, symbols_requested, bars_written,
                dataset_version, errors_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """)
        values = (
            run["id"], run["started_at"], run["status"], run["period"],
            run["symbols_requested"], run.get("bars_written", 0),
            run.get("dataset_version"), json.dumps(run.get("errors") or []),
        )
        with self.connect() as connection:
            connection.cursor().execute(statement, values)

    def complete_ingestion_run(self, run_id: str, **values: Any) -> None:
        statement = self._sql("""
            UPDATE ingestion_runs SET completed_at = ?, status = ?, bars_written = ?,
                dataset_version = ?, errors_json = ? WHERE id = ?
        """)
        parameters = (
            values.get("completed_at") or utc_now(), values["status"], values.get("bars_written", 0),
            values.get("dataset_version"), json.dumps(values.get("errors") or []), run_id,
        )
        with self.connect() as connection:
            connection.cursor().execute(statement, parameters)

    def latest_ingestion_run(self) -> Optional[Dict[str, Any]]:
        statement = """
            SELECT id, started_at, completed_at, status, period, symbols_requested,
                bars_written, dataset_version, errors_json
            FROM ingestion_runs ORDER BY started_at DESC LIMIT 1
        """
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(statement)
            rows = self._rows(cursor)
            return rows[0] if rows else None

    def market_data_summary(self, symbol: str) -> Dict[str, Any]:
        statement = self._sql("""
            SELECT COUNT(*) AS stored_bars, MIN(session_date) AS first_session,
                MAX(session_date) AS latest_session, MAX(ingested_at) AS last_persisted_at
            FROM market_bars WHERE symbol = ?
        """)
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(statement, (symbol,))
            rows = self._rows(cursor)
        return rows[0] if rows else {
            "stored_bars": 0,
            "first_session": None,
            "latest_session": None,
            "last_persisted_at": None,
        }

    def operational_symbols(self, limit: int = 100) -> List[str]:
        """Return the demand-driven universe already researched by visitors/operators."""
        safe_limit = max(1, min(int(limit), 500))
        statement = self._sql("""
            SELECT symbol, MAX(ingested_at) AS last_seen
            FROM market_bars GROUP BY symbol
            ORDER BY last_seen DESC LIMIT ?
        """)
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(statement, (safe_limit,))
            return [str(row["symbol"]) for row in self._rows(cursor)]

    def load_market_bars(self, symbol: str) -> List[Dict[str, Any]]:
        statement = self._sql("""
            SELECT session_date, open, high, low, close, adjusted_close, volume
            FROM market_bars WHERE symbol = ? ORDER BY session_date ASC
        """)
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(statement, (symbol,))
            return self._rows(cursor)

    def save_model_run(self, run: Dict[str, Any]) -> None:
        statement = self._sql("""
            INSERT INTO model_runs (
                id, symbol, model_name, artifact_path, dataset_version,
                training_start, training_end, training_rows,
                holdout_start, holdout_end, holdout_rows,
                balanced_accuracy, roc_auc, brier_score,
                metrics_json, baselines_json, features_json, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """)
        values = (
            run["id"], run["symbol"], run["model_name"], run["artifact_path"],
            run["dataset_version"], run["training_start"], run["training_end"],
            run["training_rows"], run["holdout_start"], run["holdout_end"],
            run["holdout_rows"], run["balanced_accuracy"], run.get("roc_auc"),
            run["brier_score"], json.dumps(run["metrics"], sort_keys=True),
            json.dumps(run["baselines"], sort_keys=True),
            json.dumps(run["features"], sort_keys=True), run.get("status") or "candidate",
            run.get("created_at") or utc_now(),
        )
        with self.connect() as connection:
            connection.cursor().execute(statement, values)

    def latest_model_run(self, symbol: str, status: Optional[str] = None) -> Optional[Dict[str, Any]]:
        parameters: Sequence[Any]
        if status:
            statement = self._sql("""
                SELECT * FROM model_runs WHERE symbol = ? AND status = ?
                ORDER BY created_at DESC LIMIT 1
            """)
            parameters = (symbol, status)
        else:
            statement = self._sql("""
                SELECT * FROM model_runs WHERE symbol = ? ORDER BY created_at DESC LIMIT 1
            """)
            parameters = (symbol,)
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(statement, parameters)
            rows = self._rows(cursor)
            return rows[0] if rows else None

    def model_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        statement = self._sql("SELECT * FROM model_runs WHERE id = ?")
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(statement, (run_id,))
            rows = self._rows(cursor)
            return rows[0] if rows else None

    def model_runs(self, symbol: str, limit: int = 8) -> List[Dict[str, Any]]:
        statement = self._sql("""
            SELECT * FROM model_runs WHERE symbol = ?
            ORDER BY created_at DESC LIMIT ?
        """)
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(statement, (symbol, max(1, min(int(limit), 20))))
            return self._rows(cursor)

    def approve_model_run(self, run_id: str, symbol: str) -> None:
        """Atomically keep only one approved model per symbol."""
        archive = self._sql(
            "UPDATE model_runs SET status = 'archived' WHERE symbol = ? AND status = 'approved' AND id <> ?"
        )
        approve = self._sql(
            "UPDATE model_runs SET status = 'approved' WHERE id = ? AND symbol = ? AND status = 'candidate'"
        )
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(archive, (symbol, run_id))
            cursor.execute(approve, (run_id, symbol))
            if cursor.rowcount != 1:
                raise ValueError("Only a quality-gate candidate model can be approved.")

    def upsert_prediction(self, prediction: Dict[str, Any]) -> None:
        if self.backend == "mysql":
            statement = """
                INSERT INTO predictions (
                    id, symbol, model_run_id, model_data_date, generated_at,
                    probability_up, outlook, reference_close, expected_low, expected_high,
                    actual_close, actual_direction, correct, evaluated_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    probability_up = VALUES(probability_up),
                    outlook = VALUES(outlook),
                    reference_close = VALUES(reference_close),
                    expected_low = VALUES(expected_low),
                    expected_high = VALUES(expected_high),
                    actual_close = COALESCE(predictions.actual_close, VALUES(actual_close)),
                    actual_direction = COALESCE(predictions.actual_direction, VALUES(actual_direction)),
                    correct = COALESCE(predictions.correct, VALUES(correct)),
                    evaluated_at = COALESCE(predictions.evaluated_at, VALUES(evaluated_at))
            """
        else:
            statement = self._sql("""
                INSERT INTO predictions (
                    id, symbol, model_run_id, model_data_date, generated_at,
                    probability_up, outlook, reference_close, expected_low, expected_high,
                    actual_close, actual_direction, correct, evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    probability_up = excluded.probability_up,
                    outlook = excluded.outlook,
                    reference_close = excluded.reference_close,
                    expected_low = excluded.expected_low,
                    expected_high = excluded.expected_high,
                    actual_close = COALESCE(predictions.actual_close, excluded.actual_close),
                    actual_direction = COALESCE(predictions.actual_direction, excluded.actual_direction),
                    correct = COALESCE(predictions.correct, excluded.correct),
                    evaluated_at = COALESCE(predictions.evaluated_at, excluded.evaluated_at)
            """)
        values = (
            prediction["id"], prediction["symbol"], prediction.get("model_run_id"),
            prediction["model_data_date"], prediction["generated_at"],
            prediction["probability_up"], prediction["outlook"], prediction["reference_close"],
            prediction.get("expected_low"), prediction.get("expected_high"),
            prediction.get("actual_close"), prediction.get("actual_direction"),
            prediction.get("correct"), prediction.get("evaluated_at"),
        )
        with self.connect() as connection:
            connection.cursor().execute(statement, values)

    def replace_feature_baselines(
        self, model_run_id: str, symbol: str, baselines: Iterable[Dict[str, Any]]
    ) -> None:
        rows = list(baselines)
        delete = self._sql("DELETE FROM model_feature_baselines WHERE model_run_id = ?")
        insert = self._sql("""
            INSERT INTO model_feature_baselines (
                model_run_id, symbol, feature_name, sample_count, mean_value,
                std_value, bin_edges_json, bin_proportions_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """)
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(delete, (model_run_id,))
            if rows:
                cursor.executemany(insert, [(
                    model_run_id, symbol, row["featureName"], row["sampleCount"],
                    row["mean"], row["std"], json.dumps(row["binEdges"]),
                    json.dumps(row["binProportions"]), row.get("createdAt") or utc_now(),
                ) for row in rows])

    def feature_baselines(self, model_run_id: str) -> List[Dict[str, Any]]:
        statement = self._sql("""
            SELECT model_run_id, symbol, feature_name, sample_count, mean_value,
                std_value, bin_edges_json, bin_proportions_json, created_at
            FROM model_feature_baselines WHERE model_run_id = ? ORDER BY feature_name
        """)
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(statement, (model_run_id,))
            return self._rows(cursor)

    def upsert_prediction_features(
        self,
        prediction_id: str,
        symbol: str,
        model_run_id: str,
        features: Dict[str, Any],
        observed_at: Optional[str] = None,
    ) -> int:
        rows = []
        for feature_name, raw_value in features.items():
            try:
                value = float(raw_value)
            except (TypeError, ValueError):
                continue
            if value != value or value in (float("inf"), float("-inf")):
                continue
            rows.append((
                prediction_id, symbol, model_run_id, feature_name, value,
                observed_at or utc_now(),
            ))
        if not rows:
            return 0
        if self.backend == "mysql":
            statement = """
                INSERT INTO prediction_features (
                    prediction_id, symbol, model_run_id, feature_name, feature_value, observed_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    feature_value = VALUES(feature_value),
                    observed_at = VALUES(observed_at)
            """
        else:
            statement = self._sql("""
                INSERT INTO prediction_features (
                    prediction_id, symbol, model_run_id, feature_name, feature_value, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(prediction_id, feature_name) DO UPDATE SET
                    feature_value = excluded.feature_value,
                    observed_at = excluded.observed_at
            """)
        with self.connect() as connection:
            connection.cursor().executemany(statement, rows)
        return len(rows)

    def prediction_feature_observations(
        self, symbol: str, model_run_id: str, limit_sessions: int = 60
    ) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit_sessions), 180))
        statement = self._sql("""
            SELECT pf.prediction_id, pf.feature_name, pf.feature_value,
                p.model_data_date, pf.observed_at
            FROM prediction_features pf
            JOIN predictions p ON p.id = pf.prediction_id
            WHERE pf.symbol = ? AND pf.model_run_id = ?
            ORDER BY p.model_data_date DESC, pf.feature_name ASC
        """)
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(statement, (symbol, model_run_id))
            rows = self._rows(cursor)
        selected_ids = []
        for row in rows:
            prediction_id = row["prediction_id"]
            if prediction_id not in selected_ids:
                selected_ids.append(prediction_id)
            if len(selected_ids) >= safe_limit:
                break
        allowed = set(selected_ids)
        return [row for row in rows if row["prediction_id"] in allowed]

    def save_drift_snapshot(self, snapshot: Dict[str, Any]) -> None:
        if self.backend == "mysql":
            statement = """
                INSERT INTO drift_snapshots (
                    id, symbol, model_run_id, evaluated_at, recent_observations,
                    mean_psi, max_psi, status, recommendation, details_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    evaluated_at = VALUES(evaluated_at),
                    recent_observations = VALUES(recent_observations),
                    mean_psi = VALUES(mean_psi),
                    max_psi = VALUES(max_psi),
                    status = VALUES(status),
                    recommendation = VALUES(recommendation),
                    details_json = VALUES(details_json)
            """
        else:
            statement = self._sql("""
                INSERT INTO drift_snapshots (
                    id, symbol, model_run_id, evaluated_at, recent_observations,
                    mean_psi, max_psi, status, recommendation, details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    evaluated_at = excluded.evaluated_at,
                    recent_observations = excluded.recent_observations,
                    mean_psi = excluded.mean_psi,
                    max_psi = excluded.max_psi,
                    status = excluded.status,
                    recommendation = excluded.recommendation,
                    details_json = excluded.details_json
            """)
        values = (
            snapshot["id"], snapshot["symbol"], snapshot["modelRunId"],
            snapshot["evaluatedAt"], snapshot["recentObservations"],
            snapshot.get("meanPsi"), snapshot.get("maxPsi"), snapshot["status"],
            snapshot["recommendation"], json.dumps(snapshot, sort_keys=True),
        )
        with self.connect() as connection:
            connection.cursor().execute(statement, values)

    def latest_drift_snapshot(self, symbol: str, model_run_id: str) -> Optional[Dict[str, Any]]:
        statement = self._sql("""
            SELECT details_json FROM drift_snapshots
            WHERE symbol = ? AND model_run_id = ? ORDER BY evaluated_at DESC LIMIT 1
        """)
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(statement, (symbol, model_run_id))
            rows = self._rows(cursor)
        if not rows:
            return None
        try:
            decoded = json.loads(rows[0]["details_json"])
            return decoded if isinstance(decoded, dict) else None
        except (TypeError, ValueError):
            return None

    def evaluate_pending_predictions(
        self, symbol: str, current_data_date: str, current_close: float
    ) -> int:
        select = self._sql("""
            SELECT id, outlook, reference_close FROM predictions
            WHERE symbol = ? AND model_data_date < ? AND evaluated_at IS NULL
        """)
        update = self._sql("""
            UPDATE predictions SET actual_close = ?, actual_direction = ?, correct = ?, evaluated_at = ?
            WHERE id = ?
        """)
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(select, (symbol, current_data_date))
            rows = self._rows(cursor)
            for row in rows:
                reference = float(row["reference_close"])
                actual_return = ((float(current_close) / reference) - 1) * 100 if reference else 0.0
                actual_direction = "UP" if actual_return > 0.10 else "DOWN" if actual_return < -0.10 else "FLAT"
                expected_direction = {
                    "BULLISH": "UP", "BEARISH": "DOWN", "NEUTRAL": "FLAT"
                }.get(str(row["outlook"]).upper(), "FLAT")
                cursor.execute(update, (
                    current_close, actual_direction, int(actual_direction == expected_direction),
                    utc_now(), row["id"],
                ))
            return len(rows)

    def prediction_records(self, symbol: str, limit: int = 30) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        statement = self._sql("""
            SELECT id, symbol, model_run_id, model_data_date, generated_at,
                probability_up, outlook, reference_close, expected_low, expected_high,
                actual_close, actual_direction, correct, evaluated_at
            FROM predictions WHERE symbol = ?
            ORDER BY model_data_date DESC, generated_at DESC LIMIT ?
        """)
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(statement, (symbol, safe_limit))
            return self._rows(cursor)

    def model_prediction_records(
        self, symbol: str, model_run_id: str, limit: int = 30
    ) -> List[Dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 100))
        statement = self._sql("""
            SELECT id, symbol, model_run_id, model_data_date, generated_at,
                probability_up, outlook, reference_close, expected_low, expected_high,
                actual_close, actual_direction, correct, evaluated_at
            FROM predictions WHERE symbol = ? AND model_run_id = ?
            ORDER BY model_data_date DESC, generated_at DESC LIMIT ?
        """)
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(statement, (symbol, model_run_id, safe_limit))
            return self._rows(cursor)

    def replace_document(self, source: Dict[str, Any], chunks: Iterable[Dict[str, Any]]) -> None:
        chunk_rows = list(chunks)
        delete_chunks = self._sql("DELETE FROM document_chunks WHERE document_id = ?")
        if self.backend == "mysql":
            source_statement = """
                INSERT INTO document_sources (
                    id, symbol, title, document_type, reporting_period, source_url,
                    file_sha256, page_count, chunk_count, embedding_provider, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    symbol = VALUES(symbol),
                    title = VALUES(title),
                    document_type = VALUES(document_type),
                    reporting_period = VALUES(reporting_period),
                    source_url = VALUES(source_url),
                    file_sha256 = VALUES(file_sha256),
                    page_count = VALUES(page_count),
                    chunk_count = VALUES(chunk_count),
                    embedding_provider = VALUES(embedding_provider),
                    created_at = VALUES(created_at)
            """
        else:
            source_statement = self._sql("""
                INSERT INTO document_sources (
                    id, symbol, title, document_type, reporting_period, source_url,
                    file_sha256, page_count, chunk_count, embedding_provider, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    symbol = excluded.symbol,
                    title = excluded.title,
                    document_type = excluded.document_type,
                    reporting_period = excluded.reporting_period,
                    source_url = excluded.source_url,
                    file_sha256 = excluded.file_sha256,
                    page_count = excluded.page_count,
                    chunk_count = excluded.chunk_count,
                    embedding_provider = excluded.embedding_provider,
                    created_at = excluded.created_at
            """)
        chunk_statement = self._sql("""
            INSERT INTO document_chunks (
                id, document_id, symbol, page_number, chunk_index, text,
                embedding_json, embedding_provider, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """)
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(delete_chunks, (source["id"],))
            cursor.execute(source_statement, (
                source["id"], source["symbol"], source["title"], source["document_type"],
                source.get("reporting_period"), source.get("source_url"), source["file_sha256"],
                source["page_count"], len(chunk_rows), source["embedding_provider"],
                source.get("created_at") or utc_now(),
            ))
            cursor.executemany(chunk_statement, [(
                row["id"], source["id"], source["symbol"], row["page_number"],
                row["chunk_index"], row["text"], json.dumps(row["embedding"]),
                source["embedding_provider"], source.get("created_at") or utc_now(),
            ) for row in chunk_rows])

    def document_sources(self, symbol: str) -> List[Dict[str, Any]]:
        statement = self._sql("""
            SELECT id, symbol, title, document_type, reporting_period, source_url,
                file_sha256, page_count, chunk_count, embedding_provider, created_at
            FROM document_sources WHERE symbol = ? ORDER BY created_at DESC
        """)
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(statement, (symbol,))
            return self._rows(cursor)

    def delete_documents(
        self, symbol: str, document_type: str, keep_document_id: Optional[str] = None
    ) -> int:
        conditions = "symbol = ? AND document_type = ?"
        values: List[Any] = [symbol, document_type]
        if keep_document_id:
            conditions += " AND id <> ?"
            values.append(keep_document_id)
        select_statement = self._sql(f"SELECT id FROM document_sources WHERE {conditions}")
        delete_chunks = self._sql("DELETE FROM document_chunks WHERE document_id = ?")
        delete_source = self._sql("DELETE FROM document_sources WHERE id = ?")
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(select_statement, tuple(values))
            document_ids = [row[0] for row in cursor.fetchall()]
            for document_id in document_ids:
                cursor.execute(delete_chunks, (document_id,))
                cursor.execute(delete_source, (document_id,))
        return len(document_ids)

    def document_chunks(self, symbol: str, embedding_provider: str) -> List[Dict[str, Any]]:
        statement = self._sql("""
            SELECT c.id, c.document_id, c.page_number, c.chunk_index, c.text,
                c.embedding_json, s.title, s.document_type, s.reporting_period, s.source_url
            FROM document_chunks c
            JOIN document_sources s ON s.id = c.document_id
            WHERE c.symbol = ? AND c.embedding_provider = ?
            ORDER BY c.document_id, c.page_number, c.chunk_index
        """)
        with self.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(statement, (symbol, embedding_provider))
            return self._rows(cursor)
