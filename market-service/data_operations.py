"""Read-only data-freshness evidence for the public dashboard."""

from __future__ import annotations

from datetime import date, datetime, timezone
import json
import os
from typing import Any, Dict, Optional

from persistence import Database, utc_now


FRESH_CALENDAR_DAYS = 4
WATCH_CALENDAR_DAYS = 7
MINIMUM_OFFLINE_TRAINING_BARS = 180


def _json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        decoded = json.loads(value or "[]")
        return decoded if isinstance(decoded, list) else []
    except (TypeError, ValueError):
        return []


def database_storage_snapshot(database: Optional[Database] = None) -> Dict[str, Any]:
    repository = database or Database()
    repository.initialize_schema()
    schema = repository.schema_status()
    configured_backup_policy = os.getenv("DATABASE_BACKUP_POLICY", "").strip()
    return {
        "backend": repository.backend,
        "durableAcrossDeploys": repository.backend == "postgresql",
        "retention": (
            "External PostgreSQL lifecycle"
            if repository.backend == "postgresql"
            else "Local service-instance lifecycle"
        ),
        "schema": schema,
        "backup": {
            "configured": bool(configured_backup_policy),
            "policy": configured_backup_policy or "not_configured",
            "recommendedAction": (
                "Use provider PITR plus periodic logical exports."
                if repository.backend == "postgresql"
                else "Move production data to PostgreSQL before relying on backups."
            ),
        },
        "credentialsExposed": False,
        "generatedAt": utc_now(),
    }


def data_operations_snapshot(
    symbol: str, database: Optional[Database] = None
) -> Dict[str, Any]:
    repository = database or Database()
    repository.initialize_schema()
    summary = repository.market_data_summary(symbol)
    stored_bars = int(summary.get("stored_bars") or 0)
    latest_session = summary.get("latest_session")
    latest_run = repository.latest_ingestion_run()
    storage = database_storage_snapshot(repository)

    if latest_session:
        session_date = date.fromisoformat(str(latest_session)[:10])
        calendar_age_days = max(0, (datetime.now(timezone.utc).date() - session_date).days)
        freshness = (
            "fresh" if calendar_age_days <= FRESH_CALENDAR_DAYS
            else "watch" if calendar_age_days <= WATCH_CALENDAR_DAYS
            else "stale"
        )
        message = (
            "Validated OHLCV history is ready for offline data operations."
            if freshness == "fresh"
            else "Stored history should be refreshed before a new training decision."
        )
    else:
        calendar_age_days = None
        freshness = "provider_only"
        message = (
            "Research can still use the live provider, but this symbol has no persisted "
            "history for scheduled offline operations yet."
        )

    pipeline = None
    if latest_run:
        errors = _json_list(latest_run.get("errors_json"))
        pipeline = {
            "runId": latest_run["id"],
            "status": latest_run["status"],
            "period": latest_run["period"],
            "symbolsRequested": int(latest_run["symbols_requested"]),
            "barsWritten": int(latest_run["bars_written"]),
            "datasetVersion": latest_run.get("dataset_version"),
            "errorCount": len(errors),
            "startedAt": str(latest_run["started_at"]),
            "completedAt": str(latest_run["completed_at"]) if latest_run.get("completed_at") else None,
        }

    return {
        "symbol": symbol,
        "mode": "persistent_history" if stored_bars else "runtime_provider_only",
        "freshness": freshness,
        "storedBars": stored_bars,
        "firstSession": summary.get("first_session"),
        "latestSession": latest_session,
        "calendarAgeDays": calendar_age_days,
        "lastPersistedAt": (
            str(summary["last_persisted_at"]) if summary.get("last_persisted_at") else None
        ),
        "offlineTrainingReady": stored_bars >= MINIMUM_OFFLINE_TRAINING_BARS,
        "minimumTrainingBars": MINIMUM_OFFLINE_TRAINING_BARS,
        "scheduledRefreshEligible": stored_bars > 0,
        "pipeline": pipeline,
        "storage": storage,
        "message": message,
        "thresholds": {
            "freshThroughCalendarDays": FRESH_CALENDAR_DAYS,
            "watchThroughCalendarDays": WATCH_CALENDAR_DAYS,
            "weekendHolidayBufferIncluded": True,
        },
        "generatedAt": utc_now(),
    }
