"""Create and verify a logical backup of the saved hosted MySQL database."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "market-service"))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from check_cloud_mysql import verified_mysql_url  # noqa: E402
from database_maintenance import create_backup, verify_backup  # noqa: E402
from persistence import Database  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ca-file", required=True, type=Path)
    parser.add_argument("--backup-file", required=True, type=Path)
    args = parser.parse_args()
    try:
        database_url = verified_mysql_url(
            os.environ.get("FINTRACK_CLOUD_MYSQL_URI", ""), args.ca_file
        )
        created = create_backup(args.backup_file, Database(database_url))
        verified = verify_backup(args.backup_file)
        report = {
            "status": verified["status"],
            "backend": created["backend"],
            "format": created["format"],
            "sizeBytes": created["sizeBytes"],
            "sha256": created["sha256"],
            "backupPath": created["path"],
            "manifestPath": created["manifestPath"],
            "credentialsIncluded": False,
        }
    except Exception as error:
        print(json.dumps({
            "status": "failed",
            "errorType": type(error).__name__,
            "message": "Cloud MySQL backup failed; no existing data was deleted or replaced.",
            "credentialsIncluded": False,
        }), file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
