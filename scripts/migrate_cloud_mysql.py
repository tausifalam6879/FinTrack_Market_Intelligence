"""Copy the legacy hosted database into verified-TLS MySQL without exposing secrets."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "market-service"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from check_cloud_mysql import verified_mysql_url  # noqa: E402
from database_cutover import migrate_legacy_to_mysql, write_cutover_manifest  # noqa: E402
from persistence import Database  # noqa: E402


def secured_postgres_url(raw_url: str) -> str:
    """Validate the old hosted URL and require encrypted transport."""
    parsed = urlsplit(raw_url.strip())
    if (
        parsed.scheme not in {"postgres", "postgresql"}
        or not parsed.username
        or not parsed.password
        or not parsed.hostname
        or not parsed.path.strip("/")
        or parsed.fragment
        or "CLICK_TO_REVEAL" in raw_url.upper()
    ):
        raise ValueError("Copy the complete previous PostgreSQL/Neon connection URL.")
    _ = parsed.port
    query = [(key, value) for key, value in parse_qsl(parsed.query)
             if key.lower() != "sslmode"]
    query.append(("sslmode", "require"))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def migrate(source_url: str, target_url: str, ca_file: Path, manifest_file: Path) -> dict:
    source = Database(secured_postgres_url(source_url))
    target = Database(verified_mysql_url(target_url, ca_file))
    result = migrate_legacy_to_mysql(
        source,
        target,
        confirm_empty_target=True,
    )
    manifest_path = write_cutover_manifest(result, manifest_file)
    return {**result, "manifestPath": str(manifest_path)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ca-file", required=True, type=Path)
    parser.add_argument("--manifest-file", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = migrate(
            os.environ.get("FINTRACK_LEGACY_DATABASE_URI", ""),
            os.environ.get("FINTRACK_CLOUD_MYSQL_URI", ""),
            args.ca_file,
            args.manifest_file,
        )
    except Exception as error:
        # Database-driver exceptions can include connection details. Emit only
        # a safe error category and keep both URLs out of terminal output.
        print(json.dumps({
            "status": "failed",
            "errorType": type(error).__name__,
            "message": (
                "Migration did not complete. The old database was not changed. "
                "Check the copied old DATABASE_URL and database availability."
            ),
            "credentialsIncluded": False,
        }), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
