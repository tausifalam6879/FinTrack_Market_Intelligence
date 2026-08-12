"""Persistent market-data storage for PostgreSQL with a local SQLite fallback."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence


DEFAULT_SQLITE_PATH = Path(__file__).resolve().parent / "data" / "fintrack.db"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    """Small DB-API repository that keeps SQL portable across SQLite/PostgreSQL."""

    def __init__(self, url: Optional[str] = None):
        self.url = str(url or os.getenv("DATABASE_URL") or f"sqlite:///{DEFAULT_SQLITE_PATH}")
        self.backend = "postgresql" if self.url.startswith(("postgresql://", "postgres://")) else "sqlite"

    @property
    def location(self) -> str:
        if self.backend == "postgresql":
            return "DATABASE_URL"
        return str(self._sqlite_path())

    def _sqlite_path(self) -> Path:
        prefix = "sqlite:///"
        raw_path = self.url[len(prefix):] if self.url.startswith(prefix) else self.url
        path = Path(raw_path).expanduser()
        return path if path.is_absolute() else (Path.cwd() / path).resolve()

    @contextmanager
    def connect(self) -> Iterator[Any]:
        if self.backend == "postgresql":
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
            connection.close()

    def _sql(self, statement: str) -> str:
        return statement.replace("?", "%s") if self.backend == "postgresql" else statement

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

    def initialize_schema(self) -> None:
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
            "CREATE INDEX IF NOT EXISTS idx_document_sources_symbol ON document_sources(symbol, created_at)",
            "CREATE INDEX IF NOT EXISTS idx_document_chunks_symbol ON document_chunks(symbol, embedding_provider)",
        ]
        with self.connect() as connection:
            cursor = connection.cursor()
            for statement in statements:
                cursor.execute(statement)

    def upsert_company(self, company: Dict[str, Any]) -> None:
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

    def replace_document(self, source: Dict[str, Any], chunks: Iterable[Dict[str, Any]]) -> None:
        chunk_rows = list(chunks)
        delete_chunks = self._sql("DELETE FROM document_chunks WHERE document_id = ?")
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
