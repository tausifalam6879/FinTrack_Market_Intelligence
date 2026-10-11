"""Durable, bounded demand queue. Only a trusted offline job trains candidates."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from data_pipeline import ingest_symbols, normalize_symbol
from persistence import Database, utc_now


class PreparationQueue:
    def __init__(self, database):
        self.database = database

    def initialize(self):
        with self.database.connect() as connection:
            connection.cursor().execute("""CREATE TABLE IF NOT EXISTS company_preparation (
                symbol VARCHAR(20) PRIMARY KEY, status VARCHAR(24) NOT NULL,
                attempts INTEGER NOT NULL, lease_token VARCHAR(36), lease_until VARCHAR(40),
                updated_at VARCHAR(40) NOT NULL, error_code VARCHAR(80), model_run_id VARCHAR(36)
            )""")
            cursor = connection.cursor()
            cursor.execute("CREATE TABLE IF NOT EXISTS preparation_guard (id INTEGER PRIMARY KEY)")
            insert = "INSERT IGNORE" if self.database.backend == "mysql" else "INSERT"
            statement = insert + " INTO preparation_guard (id) VALUES (1)"
            if self.database.backend != "mysql":
                statement += " ON CONFLICT(id) DO NOTHING"
            cursor.execute(statement)

    def status(self, symbol):
        with self.database.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(self.database._sql("SELECT * FROM company_preparation WHERE symbol = ?"), (normalize_symbol(symbol),))
            rows = self.database._rows(cursor)
        return rows[0] if rows else {"symbol": normalize_symbol(symbol), "status": "not_requested"}

    def enqueue(self, symbol):
        symbol = normalize_symbol(symbol)
        # One persistent row per symbol: opening a page never retries a rejected model.
        with self.database.connect() as connection:
            cursor = connection.cursor()
            if self.database.backend == "sqlite":
                cursor.execute("BEGIN IMMEDIATE")
            else:
                cursor.execute("SELECT id FROM preparation_guard WHERE id=1 FOR UPDATE")
                cursor.fetchone()
            cursor.execute(self.database._sql("SELECT status FROM company_preparation WHERE symbol=?"), (symbol,))
            existing = cursor.fetchone()
            if existing:
                return {"symbol": symbol, "status": existing[0]}
            cursor.execute("SELECT COUNT(*) FROM company_preparation WHERE status IN ('pending', 'running')")
            if int(cursor.fetchone()[0]) >= 100:
                return {"symbol": symbol, "status": "queue_full"}
            statement = ("INSERT IGNORE" if self.database.backend == "mysql" else "INSERT") + " INTO company_preparation (symbol,status,attempts,updated_at) VALUES (?, 'pending', 0, ?)"
            if self.database.backend != "mysql":
                statement += " ON CONFLICT(symbol) DO NOTHING"
            cursor.execute(self.database._sql(statement), (symbol, utc_now()))
        return self.status(symbol)

    def claim(self):
        now = utc_now()
        token = str(uuid4())
        expires = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        with self.database.connect() as connection:
            cursor = connection.cursor()
            cursor.execute(self.database._sql("""UPDATE company_preparation SET status='failed',
                error_code='LEASE_RETRIES_EXHAUSTED', updated_at=?
                WHERE status='running' AND lease_until < ? AND attempts >= 3"""), (now, now))
            cursor.execute(self.database._sql("""SELECT symbol FROM company_preparation
                WHERE attempts < 3 AND (status = 'pending' OR (status = 'running' AND lease_until < ?))
                ORDER BY updated_at LIMIT 1"""), (now,))
            row = cursor.fetchone()
            if not row:
                return None
            symbol = row[0]
            cursor.execute(self.database._sql("""UPDATE company_preparation
                SET status='running', attempts=attempts+1, lease_token=?, lease_until=?, updated_at=?
                WHERE symbol=? AND attempts < 3 AND (status='pending' OR (status='running' AND lease_until < ?))"""),
                (token, expires, now, symbol, now))
            if cursor.rowcount != 1:
                return None
        return {"symbol": symbol, "lease_token": token}

    def finish(self, claim, status, run_id=None, error_code=None):
        with self.database.connect() as connection:
            connection.cursor().execute(self.database._sql("""UPDATE company_preparation
                SET status=?, model_run_id=?, error_code=?, lease_until=NULL, updated_at=?
                WHERE symbol=? AND lease_token=? AND status='running'"""),
                (status, run_id, error_code, utc_now(), claim["symbol"], claim["lease_token"]))


def process_queue(database, limit=3):
    # Deferred import: serving containers do not need PyTorch or MLflow.
    from offline_training import train_symbol
    database.initialize_schema()
    queue = PreparationQueue(database)
    queue.initialize()
    results = []
    for _ in range(max(1, min(limit, 10))):
        claim = queue.claim()
        if not claim:
            break
        symbol = claim["symbol"]
        try:
            ingestion = ingest_symbols([symbol], database=database)
            if not any(row.get("status") == "stored" for row in ingestion.get("results", [])):
                raise RuntimeError("INGESTION_UNAVAILABLE")
            result = train_symbol(symbol, database)
            status = result.get("status")
            if status not in {"candidate", "rejected"}:
                raise RuntimeError("UNEXPECTED_TRAINING_STATUS")
            queue.finish(claim, status, result.get("modelRunId"))
        except Exception as error:
            # Never place database URLs, credentials or provider response bodies in public status.
            status = "failed"
            queue.finish(claim, status, error_code=type(error).__name__)
        results.append({"symbol": symbol, "status": status})
    return {"results": results, "automaticApproval": False, "completedAt": utc_now()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare queued companies in a trusted offline training job.")
    parser.add_argument("--limit", type=int, default=3)
    args = parser.parse_args()
    result = process_queue(Database(), args.limit)
    print(json.dumps(result), flush=True)
    if any(row["status"] == "failed" for row in result["results"]):
        raise SystemExit(1)
