"""Small in-process operational telemetry without user or request-content storage."""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Deque, Dict


_lock = Lock()
_started_at = datetime.now(timezone.utc)
_latencies_ms: Deque[float] = deque(maxlen=500)
_routes: Dict[str, Dict[str, float]] = defaultdict(lambda: {"requests": 0, "errors": 0, "totalMs": 0.0})
_llm = {"requests": 0, "accepted": 0, "groundingFallbacks": 0, "offlineFallbacks": 0}


def record_request(route: str, status_code: int, latency_ms: float) -> None:
    """Record aggregate route status and latency; never store parameters, symbols or bodies."""
    safe_route = route if route.startswith("/") else "/unknown"
    with _lock:
        _latencies_ms.append(float(latency_ms))
        item = _routes[safe_route]
        item["requests"] += 1
        item["errors"] += 1 if status_code >= 500 else 0
        item["totalMs"] += float(latency_ms)


def record_llm(status: str, accepted: bool) -> None:
    with _lock:
        _llm["requests"] += 1
        _llm["accepted"] += 1 if accepted else 0
        _llm["groundingFallbacks"] += 1 if status == "grounding_fallback" else 0
        _llm["offlineFallbacks"] += 1 if status == "offline" else 0


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 2)


def telemetry_snapshot() -> Dict[str, Any]:
    with _lock:
        latencies = list(_latencies_ms)
        routes = [
            {
                "route": route,
                "requests": int(item["requests"]),
                "errors": int(item["errors"]),
                "averageLatencyMs": round(item["totalMs"] / item["requests"], 2) if item["requests"] else None,
            }
            for route, item in _routes.items()
        ]
        llm = dict(_llm)

    total_requests = sum(item["requests"] for item in routes)
    total_errors = sum(item["errors"] for item in routes)
    llm_requests = llm["requests"]
    return {
        "privacy": "aggregate-only; no questions, symbols, IP addresses or personal data stored",
        "startedAt": _started_at.isoformat(),
        "api": {
            "totalRequests": total_requests,
            "serverErrors": total_errors,
            "errorRatePercent": round(total_errors / total_requests * 100, 2) if total_requests else 0.0,
            "latencySampleSize": len(latencies),
            "averageLatencyMs": round(sum(latencies) / len(latencies), 2) if latencies else None,
            "p50LatencyMs": _percentile(latencies, 0.50),
            "p95LatencyMs": _percentile(latencies, 0.95),
            "routes": sorted(routes, key=lambda item: item["requests"], reverse=True)[:10],
        },
        "languageModel": {
            **llm,
            "acceptedRatePercent": round(llm["accepted"] / llm_requests * 100, 2) if llm_requests else None,
            "fallbackRatePercent": round((llm["groundingFallbacks"] + llm["offlineFallbacks"]) / llm_requests * 100, 2) if llm_requests else None,
        },
        "generatedAt": datetime.now(timezone.utc).isoformat(),
    }
