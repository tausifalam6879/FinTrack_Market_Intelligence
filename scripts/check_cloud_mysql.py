"""Check a hosted MySQL connection without changing its schema or data."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import ssl
import sys
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "market-service"))
from persistence import Database  # noqa: E402


def verified_mysql_url(raw_url: str, ca_file: Path) -> str:
    """Attach the selected CA and require certificate/hostname verification."""
    parsed = urlsplit(raw_url.strip())
    if (
        parsed.scheme not in {"mysql", "mysql+pymysql"}
        or not parsed.username
        or not parsed.password
        or not parsed.hostname
        or not parsed.path.strip("/")
        or parsed.fragment
        or "CLICK_TO_REVEAL_PASSWORD" in raw_url.upper()
    ):
        raise ValueError("Copy the complete MySQL Service URI with its actual credentials.")
    if parsed.hostname.lower() in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Use the cloud MySQL Service URI, not the local database URL.")
    _ = parsed.port  # Validate the port without exposing the URI in an error.
    certificate = Path(ca_file).resolve(strict=True)
    ssl.create_default_context(cafile=str(certificate))
    tls_parameters = {"ssl", "sslmode", "ssl-mode", "ssl-ca"}
    query = [(key, value) for key, value in parse_qsl(parsed.query)
             if key.lower() not in tls_parameters]
    query.extend([
        ("ssl-mode", "VERIFY_IDENTITY"),
        ("ssl-ca", str(certificate)),
    ])
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def check_connection(raw_url: str, ca_file: Path) -> dict:
    database_url = verified_mysql_url(raw_url, ca_file)
    parsed = urlsplit(database_url)
    database = Database(database_url)
    with database.connect() as connection:
        cursor = connection.cursor()
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute("SELECT VERSION(), DATABASE()")
        version, database_name = cursor.fetchone()
        cursor.execute("SHOW SESSION STATUS LIKE 'Ssl_cipher'")
        cipher_row = cursor.fetchone()
        if not cipher_row or not cipher_row[1]:
            raise RuntimeError("The database connection is not encrypted.")
        cursor.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = %s",
            (database_name,),
        )
        table_count = int(cursor.fetchone()[0])
    return {
        "status": "connected",
        "backend": "mysql",
        "host": parsed.hostname,
        "port": parsed.port or 3306,
        "database": database_name,
        "serverVersion": version,
        "tlsVerified": True,
        "readOnlyCheck": True,
        "tableCount": table_count,
        "checkedAt": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ca-file", required=True, type=Path)
    parser.add_argument("--report-file", type=Path)
    args = parser.parse_args()
    try:
        report = check_connection(os.environ.get("FINTRACK_CLOUD_MYSQL_URI", ""), args.ca_file)
        if args.report_file:
            args.report_file.parent.mkdir(parents=True, exist_ok=True)
            args.report_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except Exception as error:
        # Driver errors may contain server data or credentials; do not echo them.
        print(json.dumps({
            "status": "failed",
            "errorType": type(error).__name__,
            "message": "Check the complete Service URI, CA certificate and current public IP allowlist.",
            "credentialsIncluded": False,
        }), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
