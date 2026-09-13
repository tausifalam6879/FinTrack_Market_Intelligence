"""Verify a backup in a disposable, network-isolated MySQL 8.4 container."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    args = parser.parse_args()
    backup = args.backup.resolve(strict=True)
    manifest = json.loads(backup.with_suffix(backup.suffix + ".manifest.json").read_text())
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    if manifest.get("format") != "mysql-sql" or manifest.get("sha256") != digest:
        raise SystemExit("Backup format or checksum verification failed.")
    name = "fintrack-restore-" + uuid.uuid4().hex[:12]

    def run(*cmd: str, **kwargs):
        return subprocess.run(cmd, check=True, capture_output=True, timeout=180, **kwargs)

    def query(sql: str) -> str:
        return run("docker", "exec", name, "mysql", "-uroot", "--batch",
                   "--skip-column-names", "fintrack_restore", "-e", sql).stdout.decode().strip()

    created = False
    try:
        # No host ports, no network, and no persistent database volume. Empty
        # root password is restricted to this throwaway container's socket.
        run("docker", "run", "-d", "--rm", "--name", name, "--network", "none",
            "--memory", "768m", "--cpus", "1", "--tmpfs", "/var/lib/mysql",
            "-e", "MYSQL_ALLOW_EMPTY_PASSWORD=yes", "-e", "MYSQL_DATABASE=fintrack_restore",
            "mysql:8.4")
        created = True
        deadline = time.monotonic() + 120
        while True:
            try:
                if query("SELECT 1") == "1":
                    # Initialization uses a temporary socket server; wait for
                    # the final server before attempting restore.
                    logs = run("docker", "logs", name)
                    if b"MySQL init process done" in logs.stdout + logs.stderr:
                        break
            except subprocess.CalledProcessError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError("Disposable MySQL did not become ready.")
            time.sleep(2)
        if query("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=DATABASE()") != "0":
            raise RuntimeError("Restore target is not empty.")
        with backup.open("rb") as stream:
            run("docker", "exec", "-i", name, "mysql", "-uroot", "fintrack_restore", stdin=stream)
        tables = query("SHOW TABLES").splitlines()
        counts = {table: int(query("SELECT COUNT(*) FROM `" + table.replace("`", "``") + "`"))
                  for table in tables}
        if not tables:
            raise RuntimeError("Restore produced no tables.")
        checks = query("CHECK TABLE " + ",".join("`" + t.replace("`", "``") + "`" for t in tables))
        if any(not line.endswith("\tstatus\tOK") for line in checks.splitlines()):
            raise RuntimeError("Restored table integrity check failed.")
        report = {"status": "restore_verified", "backupSha256": digest,
                  "mysqlVersion": query("SELECT VERSION()"), "tableCount": len(tables),
                  "rowCounts": counts, "productionModified": False,
                  "scope": "SQL restore and table integrity; not a full application rehearsal"}
        report_path = backup.with_suffix(backup.suffix + ".restore-report.json")
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    except subprocess.CalledProcessError as error:
        # Do not echo SQL or row data from database client diagnostics.
        raise SystemExit("Restore rehearsal command failed (exit %s); no production database was used."
                         % error.returncode) from None
    finally:
        if created:
            run("docker", "stop", "--time", "10", name)


if __name__ == "__main__":
    main()
