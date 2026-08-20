"""Read-only production smoke checks for API, gateway, batch comparison and PostgreSQL readiness."""

from __future__ import annotations

import argparse
import json
import sys
from urllib.request import Request, urlopen


def request_json(url: str, body: dict | None = None, timeout: int = 120) -> dict:
    encoded = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(url, data=encoded, headers={"Content-Type": "application/json"}, method="POST" if body else "GET")
    with urlopen(request, timeout=timeout) as response:
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify a deployed FinTrack service without mutation calls.")
    parser.add_argument("--api", default="https://fintrack-market-intelligence-api.onrender.com")
    parser.add_argument("--gateway", default="", help="Optional deployed Spring Boot gateway URL.")
    parser.add_argument("--require-postgres", action="store_true")
    args = parser.parse_args()
    api = args.api.rstrip("/")

    readiness = request_json(f"{api}/health/ready")
    database = readiness["checks"]["database"]
    assert readiness["status"] == "ready", readiness
    assert database["schemaVersion"] == database["expectedSchemaVersion"] == 4, database
    if args.require_postgres:
        assert database["backend"] == "postgresql", database
        assert database["durableAcrossDeploys"] is True, database
        assert database["durabilityRequired"] is True, database

    operations = request_json(f"{api}/market/operations-status")
    assert "telemetry" in operations and "api" in operations["telemetry"], operations
    comparison = request_json(f"{api}/market/compare", {"symbols": ["^NSEI", "^BSESN"], "refresh": False})
    assert len(comparison["items"]) >= 1, comparison
    assert comparison["execution"] in {"parallel-fastapi-fallback", "parallel-spring-webclient"}, comparison

    gateway = None
    if args.gateway:
        gateway_url = args.gateway.rstrip("/")
        gateway = request_json(f"{gateway_url}/health/ready")
        assert gateway["status"] == "ready" and gateway["upstream"] == "ready", gateway
        gateway_comparison = request_json(
            f"{gateway_url}/market/compare", {"symbols": ["^NSEI", "^BSESN"], "refresh": False}
        )
        assert gateway_comparison["execution"] == "parallel-spring-webclient", gateway_comparison

    print(json.dumps({
        "status": "passed",
        "api": api,
        "databaseBackend": database["backend"],
        "durableAcrossDeploys": database["durableAcrossDeploys"],
        "batchComparison": comparison["execution"],
        "gateway": gateway["status"] if gateway else "not-requested",
    }, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, OSError, ValueError, KeyError, RuntimeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, indent=2), file=sys.stderr)
        raise SystemExit(1)
