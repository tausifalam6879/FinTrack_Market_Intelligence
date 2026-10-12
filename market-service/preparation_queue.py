"""Durable, bounded demand queue. Only a trusted offline job trains candidates."""
import argparse
import json
import os
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
            cursor.execute(self.database._sql("SELECT * FROM company_preparation WHERE symbol=?"), (symbol,))
            existing = self.database._rows(cursor)
            if existing:
                return existing[0]
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

    def retry(self, symbol):
        """Explicit operator retry; browser requests cannot reset rejected runs."""
        symbol = normalize_symbol(symbol)
        with self.database.connect() as connection:
            cursor = connection.cursor()
            if self.database.backend == "sqlite":
                cursor.execute("BEGIN IMMEDIATE")
            else:
                cursor.execute("SELECT id FROM preparation_guard WHERE id=1 FOR UPDATE")
                cursor.fetchone()
            cursor.execute("SELECT COUNT(*) FROM company_preparation WHERE status IN ('pending', 'running')")
            if int(cursor.fetchone()[0]) >= 100:
                return {"symbol": symbol, "status": "queue_full"}
            cursor.execute(self.database._sql("""UPDATE company_preparation
                SET status='pending', attempts=0, lease_token=NULL, lease_until=NULL,
                    error_code=NULL, model_run_id=NULL, updated_at=?
                WHERE symbol=? AND status IN ('failed','rejected','candidate')"""), (utc_now(), symbol))
        return self.status(symbol)


def automatic_approval_enabled():
    return os.getenv("PREPARATION_APPROVE_PASSING", "false").lower() == "true"


def eligible_for_automatic_approval(result):
    """Additional constraints; the registry still checks gate and artifact identity."""
    holdout = result.get("untouchedHoldout") or {}
    return (result.get("status") == "candidate"
            and result.get("qualityGate", {}).get("passed") is True
            and result.get("probabilityMethod") == "chronological_sigmoid_v1"
            and holdout.get("rows", 0) >= 60
            and holdout.get("brierScore", 1) < 0.25)


def seed_uncovered_symbols(database):
    """One-time migration to calibrated training; never repeatedly retry v1 failures."""
    from offline_training import stored_training_universe
    queue = PreparationQueue(database)
    queue.initialize()
    results = []
    for symbol in stored_training_universe(database)["eligible"]:
        if database.latest_model_run(symbol, "approved"):
            continue
        latest = database.latest_model_run(symbol)
        metrics = json.loads(latest.get("metrics_json") or "{}") if latest else {}
        if metrics.get("probabilityMethod") == "chronological_sigmoid_v1":
            continue
        status = queue.enqueue(symbol)
        if status["status"] in {"candidate", "rejected", "failed"}:
            status = queue.retry(symbol)
        results.append({"symbol": symbol, "status": status["status"]})
    return {"status": "coverage_queued", "results": results, "trainingStarted": False}


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
            ingestion = ingest_symbols([symbol], period="5y", database=database)
            if not any(row.get("status") == "stored" for row in ingestion.get("results", [])):
                raise RuntimeError("INGESTION_UNAVAILABLE")
            result = train_symbol(symbol, database)
            status = result.get("status")
            if status not in {"candidate", "rejected"}:
                raise RuntimeError("UNEXPECTED_TRAINING_STATUS")
            if automatic_approval_enabled() and eligible_for_automatic_approval(result):
                from model_registry import approve_model
                approve_model(result["modelRunId"], database)
                status = "approved"
            queue.finish(claim, status, result.get("modelRunId"))
        except Exception as error:
            # Never place database URLs, credentials or provider response bodies in public status.
            status = "failed"
            queue.finish(claim, status, error_code=type(error).__name__)
        results.append({"symbol": symbol, "status": status})
    return {"results": results, "automaticApproval": automatic_approval_enabled(), "completedAt": utc_now()}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare queued companies in a trusted offline training job.")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--retry-symbols", nargs="+", help="Explicitly requeue terminal results; at most 10 symbols per invocation.")
    parser.add_argument("--seed-stored", action="store_true", help="Queue stored symbols without approved or already calibrated models, then exit.")
    parser.add_argument("--check-only", action="store_true", help="Verify dependencies and database queue without ingestion or training.")
    args = parser.parse_args()
    if args.seed_stored:
        if args.retry_symbols or args.check_only:
            parser.error("--seed-stored is a separate operation")
        print(json.dumps(seed_uncovered_symbols(Database())), flush=True)
        raise SystemExit(0)
    if args.retry_symbols:
        if len(args.retry_symbols) > 10 or args.check_only:
            parser.error("Use at most 10 retry symbols without --check-only")
        queue = PreparationQueue(Database())
        queue.initialize()
        for symbol in args.retry_symbols:
            queue.retry(symbol)
    if args.check_only:
        import torch
        database = Database()
        database.ping()
        queue = PreparationQueue(database)
        queue.initialize()
        with database.connect() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT status, COUNT(*) AS count FROM company_preparation GROUP BY status")
            counts = database._rows(cursor)
        print(json.dumps({"status": "ready", "queueCounts": counts,
                          "torchVersion": torch.__version__, "trainingStarted": False,
                          "automaticApproval": automatic_approval_enabled()}), flush=True)
        raise SystemExit(0)
    result = process_queue(Database(), args.limit)
    print(json.dumps(result), flush=True)
    if any(row["status"] == "failed" for row in result["results"]):
        raise SystemExit(1)
