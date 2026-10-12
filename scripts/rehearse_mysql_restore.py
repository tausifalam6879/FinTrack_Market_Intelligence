"""Verify a backup in a disposable, network-isolated MySQL 8.4 container."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import uuid


def decode_model_record(record: str) -> dict:
    """HEX transport avoids mysql --batch escaping nested JSON backslashes."""
    return json.loads(bytes.fromhex(record).decode("utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path)
    parser.add_argument("--application", action="store_true",
                        help="Also test prebuilt fintrack-rehearsal-api/gateway:local images.")
    parser.add_argument("--models", action="store_true", help="Recover approved GCS artifacts and test inference in the isolated API.")
    parser.add_argument("--browser", action="store_true", help="Run prebuilt React/Chromium recovery image against restored gateway.")
    parser.add_argument("--external-ai", action="store_true", help="Test actual Gemini with public restored market evidence; requires gcloud secret access.")
    parser.add_argument("--project", default="project-424147c2-3cf6-4c26-b18")
    args = parser.parse_args()
    if (args.models or args.browser or args.external_ai) and not args.application:
        parser.error("Recovery extensions require --application")
    backup = args.backup.resolve(strict=True)
    manifest = json.loads(backup.with_suffix(backup.suffix + ".manifest.json").read_text())
    digest = hashlib.sha256(backup.read_bytes()).hexdigest()
    if manifest.get("format") != "mysql-sql" or manifest.get("sha256") != digest:
        raise SystemExit("Backup format or checksum verification failed.")
    name = "fintrack-restore-" + uuid.uuid4().hex[:12]
    network = name + "-net"
    application_containers = []
    network_created = False

    def run(*cmd: str, **kwargs):
        return subprocess.run(cmd, check=True, capture_output=True, timeout=kwargs.pop("timeout", 180), **kwargs)

    def query(sql: str) -> str:
        return run("docker", "exec", name, "mysql", "-uroot", "--batch",
                   "--skip-column-names", "fintrack_restore", "-e", sql).stdout.decode().strip()

    created = False
    try:
        if args.application:
            run("docker", "network", "create", "--internal", network)
            network_created = True
        # No host ports, no network, and no persistent database volume. Empty
        # root password is restricted to this throwaway container's socket.
        password = uuid.uuid4().hex
        run("docker", "run", "-d", "--rm", "--name", name, "--network", network if args.application else "none",
            "--memory", "768m", "--cpus", "1", "--tmpfs", "/var/lib/mysql",
            "-e", "MYSQL_ALLOW_EMPTY_PASSWORD=yes", "-e", "MYSQL_DATABASE=fintrack_restore",
            "-e", "MYSQL_USER=rehearsal", "-e", "MYSQL_PASSWORD=" + password,
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
        if args.application:
            api = name + "-api"
            gateway = name + "-gateway"
            recovered_models = []
            if args.models:
                records = query("SELECT HEX(JSON_OBJECT('symbol',symbol,'uri',artifact_path,'metrics',metrics_json)) FROM model_runs WHERE status='approved'").splitlines()
                if not records or len(records) > 50:
                    raise RuntimeError("Expected between 1 and 50 approved model records in backup.")
                artifact_dir = backup.parent / (name + "-artifacts")
                artifact_dir.mkdir(mode=0o700)
                for record in records:
                    row = decode_model_record(record)
                    metrics = json.loads(row["metrics"]) if isinstance(row["metrics"], str) else row["metrics"]
                    checksum = metrics.get("artifactSha256", "")
                    uri = row["uri"]
                    if not isinstance(uri, str) or not uri.startswith("gs://fintrack-models-304232323336/models/") or not uri.endswith(".joblib"):
                        raise RuntimeError("Restored artifact is outside the trusted model bucket.")
                    if len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
                        raise RuntimeError("Invalid registered artifact checksum.")
                    target = artifact_dir / (checksum + ".joblib")
                    run("gcloud", "storage", "cp", uri, str(target))
                    if hashlib.sha256(target.read_bytes()).hexdigest() != checksum:
                        raise RuntimeError("Recovered model checksum mismatch.")
                    target.chmod(0o644)
                    recovered_models.append(row["symbol"])
            run("docker", "run", "-d", "--rm", "--name", api, "--network", network,
                "--memory", "2g", "--cpus", "1",
                "-e", "MYSQL_HOST=" + name, "-e", "MYSQL_PORT=3306",
                "-e", "MYSQL_DATABASE=fintrack_restore", "-e", "MYSQL_USER=rehearsal",
                "-e", "MYSQL_PASSWORD=" + password, "-e", "REQUIRE_DURABLE_DATABASE=true",
                "-e", "LLM_PROVIDER=offline",
                "-e", "MARKET_DATA_MODE=stored",
                "-e", "MODEL_ARTIFACT_BUCKET=fintrack-models-304232323336",
                "fintrack-rehearsal-api:local")
            application_containers.append(api)
            if args.models:
                for target in artifact_dir.glob("*.joblib"):
                    run("docker", "cp", str(target), api + ":/app/artifacts/" + target.name)
            run("docker", "run", "-d", "--rm", "--name", gateway, "--network", network,
                "--memory", "1g", "--cpus", "1",
                "-e", "FINTRACK_GATEWAY_UPSTREAM_BASE_URL=http://" + api + ":8000",
                "fintrack-rehearsal-gateway:local")
            application_containers.append(gateway)

            def request(base, path):
                code = "import urllib.request; print(urllib.request.urlopen(" + repr(base + path) + ",timeout=10).read().decode())"
                return json.loads(run("docker", "exec", api, "python", "-c", code).stdout)

            def ready(base):
                until = time.monotonic() + 120
                while time.monotonic() < until:
                    try:
                        result = request(base, "/health/ready")
                        if result.get("status") == "ready":
                            return result
                    except subprocess.CalledProcessError:
                        pass
                    time.sleep(2)
                raise RuntimeError("Application readiness timed out.")

            api_health = ready("http://127.0.0.1:8000")
            gateway_health = ready("http://" + gateway + ":8080")
            # Select any restored company instead of hard-coding a particular listing.
            # Prefer an explicit ticker that the UI can open without an online
            # company-directory lookup; still select from actual restored data.
            symbol = query("SELECT symbol FROM market_bars GROUP BY symbol ORDER BY CASE WHEN symbol LIKE '^%' OR symbol LIKE '%.NS' OR symbol LIKE '%.BO' THEN 0 ELSE 1 END, COUNT(*) DESC, symbol LIMIT 1")
            from urllib.parse import quote
            data = request("http://" + gateway + ":8080", "/market/data-operations?symbol=" + quote(symbol, safe=""))
            expected_bars = int(query("SELECT COUNT(*) FROM market_bars WHERE symbol='" + symbol.replace("'", "''") + "'"))
            if expected_bars == 0 or data.get("storedBars") != expected_bars:
                raise RuntimeError("Gateway data does not match restored history.")
            report["application"] = {"api": api_health["status"],
                "database": api_health["checks"]["database"]["status"],
                "gateway": gateway_health["status"], "verifiedSymbol": symbol, "verifiedStoredBars": expected_bars}
            report["scope"] = "Restored database + API + gateway + stored history route; external AI and browser UI not tested"
            report["status"] = "application_restore_verified"
            if args.models:
                code = (Path(__file__).parent / "check_recovered_models.py").read_text(encoding="utf-8")
                tested = json.loads(run("docker", "exec", api, "python", "-c", code,
                                        json.dumps(sorted(set(recovered_models)))).stdout)
                report["models"] = tested
                report["status"] = "model_application_restore_verified"
                report["scope"] += "; approved artifacts checksum-verified and inference tested on stored reference features, not live provider data"
            if args.browser:
                browser_name = name + "-browser"
                application_containers.append(browser_name)
                output = run("docker", "run", "--name", browser_name, "--network", network,
                             "--memory", "2g", "--cpus", "1", "--shm-size", "256m",
                             "fintrack-rehearsal-browser:local", "node", "recovery/browser-check.mjs",
                             "http://" + gateway + ":8080", symbol, timeout=300)
                lines = [json.loads(line) for line in output.stdout.decode().splitlines() if line.startswith('{')]
                report["browser"] = next(item for item in lines if item.get("status") == "browser_recovery_verified")
                report["status"] = "browser_application_restore_verified"
                report["scope"] = report["scope"].replace("external AI and browser UI not tested", "React browser research verified; external AI not tested")
                run("docker", "cp", browser_name + ":/tmp/recovery-browser/research.png", str(backup.parent / "recovered-browser.png"))
            if args.external_ai:
                service = json.loads(run("gcloud", "run", "services", "describe", "fintrack-market-api",
                                         "--project", args.project, "--region", "asia-south1", "--format=json").stdout)
                settings = {}
                for entry in service["spec"]["template"]["spec"]["containers"][0].get("env", []):
                    if entry["name"] not in {"GEMINI_API_KEY", "GEMINI_MODEL", "LLM_MODEL"}:
                        continue
                    if "value" in entry:
                        settings[entry["name"]] = entry["value"]
                    else:
                        secret = entry.get("valueFrom", {}).get("secretKeyRef", {})
                        if secret:
                            settings[entry["name"]] = run("gcloud", "secrets", "versions", "access", secret["key"],
                                "--secret", secret["name"], "--project", args.project).stdout.decode().strip()
                if not settings.get("GEMINI_API_KEY"):
                    raise RuntimeError("Serving Gemini credential configuration was not found")
                # Only API receives temporary outbound connectivity. The database
                # stays on the internal network with disposable credentials.
                run("docker", "network", "connect", "bridge", api)
                code = (Path(__file__).parent / "check_recovered_ai.py").read_text(encoding="utf-8")
                report["externalAI"] = json.loads(run("docker", "exec", "-i", api, "python", "-c", code,
                    input=json.dumps(settings).encode()).stdout)
                settings.clear()
                report["scope"] = report["scope"].replace("external AI and browser UI not tested", "real Gemini verified; browser UI not tested").replace("external AI not tested", "real Gemini verified")
            if args.browser and args.external_ai:
                report["status"] = "extended_application_restore_verified"
                report["scope"] = "Restored SQL, API, gateway, React browser research and real Gemini on restored public market evidence; model checks reported separately."
        report_path = backup.with_suffix(backup.suffix + ".restore-report.json")
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, indent=2))
    except subprocess.CalledProcessError as error:
        # Do not echo SQL or row data from database client diagnostics.
        if "recovery/browser-check.mjs" in error.cmd:
            print(error.stderr.decode(errors="replace")[-5000:], file=__import__('sys').stderr)
        raise SystemExit("Restore rehearsal command failed (exit %s); no production database was used."
                         % error.returncode) from None
    finally:
        for container in reversed(application_containers):
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=30)
        if created:
            run("docker", "stop", "--time", "10", name)
        if network_created:
            run("docker", "network", "rm", network)


if __name__ == "__main__":
    main()
