"""Read-only TLS MySQL dump to private Cloud Storage; never restores production."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import unquote, urlparse


def dump_command(url, target):
    parsed = urlparse(url)
    if parsed.scheme not in {"mysql", "mysql+pymysql"} or not parsed.hostname or not parsed.username or not parsed.path.strip("/"):
        raise ValueError("Incomplete MySQL configuration")
    env = os.environ.copy()
    env["MYSQL_PWD"] = unquote(parsed.password or "")
    return ["mysqldump", "--single-transaction", "--skip-lock-tables", "--no-tablespaces",
            "--set-gtid-purged=OFF", "--column-statistics=0", "--triggers",
            "--ssl-mode=VERIFY_IDENTITY", "--ssl-ca=/etc/secrets/ca.pem",
            "--host=" + parsed.hostname, "--port=" + str(parsed.port or 3306),
            "--user=" + unquote(parsed.username), "--result-file=" + str(target),
            unquote(parsed.path.strip("/"))], env


def main():
    from google.cloud import storage
    bucket_name = os.environ["BACKUP_BUCKET"]
    object_name = os.environ["BACKUP_OBJECT"]
    if not object_name.startswith("rehearsals/") or not object_name.endswith(".sql") or ".." in object_name:
        raise ValueError("Unexpected backup object")
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory) / "backup.sql"
        command, env = dump_command(os.environ["DATABASE_URL"], target)
        subprocess.run(command, env=env, check=True, capture_output=True, timeout=900)
        size = target.stat().st_size
        if not size:
            raise RuntimeError("Empty backup")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        manifest = {"format": "mysql-sql", "backend": "mysql", "sha256": digest,
                    "sizeBytes": size, "containsCredentials": False,
                    "scope": "Tables and triggers; routines and full application restore not verified"}
        bucket = storage.Client().bucket(bucket_name)
        bucket.blob(object_name).upload_from_filename(str(target), if_generation_match=0)
        bucket.blob(object_name + ".manifest.json").upload_from_string(
            json.dumps(manifest), content_type="application/json", if_generation_match=0)
        print(json.dumps({"status": "backup_uploaded", "object": object_name,
                          "sha256": digest, "sizeBytes": size, "productionRestore": False}), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(json.dumps({"status": "failed", "errorType": type(error).__name__,
                          "message": "Backup failed. Credentials and SQL diagnostics withheld."}), flush=True)
        raise SystemExit(1) from None
