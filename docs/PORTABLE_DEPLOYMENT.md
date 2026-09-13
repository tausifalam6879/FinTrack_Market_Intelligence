# Placement demo continuity and migration

Current production: GitHub Pages -> Cloud Run Spring gateway -> Cloud Run
Python API -> Aiven MySQL. Retain Aiven; no Cloud SQL migration is needed.
The Google trial console showed expiry on 11 December 2026. Credits can run out
earlier. SQL restore was rehearsed on 13 September 2026 using MySQL 8.4.11:
11 tables passed integrity checks, including 6,047 market bars and 25 predictions.
The temporary test database was removed; the private backup and report remain
under backups/cloud-mysql. Full application migration is still a separate test.

## Keep the current deployment running

- Keep request-based billing and one warm revision per service. Current API:
  1 CPU / 2 GiB; gateway: 1 CPU / 1 GiB. Revision maximum is 2; service maximum
  is 3. Old tagged warm revisions may add cost; inspect them after deployments.
- Check gross usage before trial credits in Billing reports, including other
  projects sharing the billing account. Budget alerts are notifications, not
  spending caps. Do not activate a paid account for this trial-only plan.
- Preserve current Cloud Run image digests and private environment settings.
  DATABASE_URL and GEMINI_API_KEY come from Secret Manager; the Aiven CA is
  mounted at /etc/secrets/ca.pem. Never commit secret values or database dumps.
- Aiven's broad IP allowlist remains unresolved. A restricted allowlist needs
  a verified egress IP. Do not remove working access before validating the new
  network path. NAT is a separate cost decision, not required by this runbook.

## Move to a Docker host while keeping Aiven

Use Docker Compose 2.30 or newer. The original compose.yaml remains a local
MySQL/MLflow development stack. compose.portable.yaml is a separate deployment
using the existing external database and only the API and gateway.

1. Clone this repository at the intended tested commit on the destination.
2. Privately copy portable.env.example to .env.portable and fill in credentials.
   Preserve the existing DATABASE_URL SSL parameters; point its CA path at
   /etc/secrets/ca.pem. Values are raw, without shell quotes. Create
   secrets/aiven-ca.pem using the genuine Aiven CA certificate.
3. If Aiven is IP-restricted, add the destination's stable outbound IP before
   startup. Keep the old host allowed until the new host is verified.
4. Start from the repository root:

   ```sh
   docker compose -f compose.portable.yaml config --quiet
   docker compose -f compose.portable.yaml up -d --build
   docker compose -f compose.portable.yaml ps
   curl --fail http://127.0.0.1:8081/health/ready
   curl --fail 'http://127.0.0.1:8081/market/analysis?symbol=INFY.NS&refresh=false'
   ```

5. For a public demo, configure a trusted HTTPS reverse proxy on the new host
   targeting 127.0.0.1:8081. The API and database are not published by this stack.
   Configure HTTPS before changing the frontend; GitHub Pages cannot call HTTP.
6. Change VITE_MARKET_API_BASE_URL in .github/workflows/deploy-pages.yml to the
   new HTTPS gateway, deploy Pages, and test company research plus an assistant
   question in the browser. The current allowed Pages origin remains valid.
7. Retain the old endpoint for rollback until the new host works. To roll back,
   restore the previous frontend URL and redeploy Pages.

The local frontend can instead use http://localhost:8081. An offline laptop
demo needs a separately restored local database and local market data; keeping
Aiven still requires internet. Gemini also requires internet. This stack does
not install Ollama or guarantee offline AI answers.

## Backup and recovery

For a repeatable SQL restore rehearsal with Docker running:

```sh
docker pull mysql:8.4
python scripts/rehearse_mysql_restore.py backups/cloud-mysql/YOUR_BACKUP.sql
```

This verifies the checksum, restores into a new network-isolated MySQL container,
checks every restored table, and saves a private `.restore-report.json` beside
the backup. Its temporary database is removed when the test finishes. It does
not connect to Aiven or perform a full application/UI migration test.

Existing scripts/backup_cloud_mysql.py creates a logical dump and checksum
manifest using FINTRACK_CLOUD_MYSQL_URI supplied privately in the environment.
Use --ca-file with the genuine CA and --backup-file with a private output path.
Keep the SQL dump and its manifest together in an encrypted backup location
outside Google Cloud. Verify it with market-service/database_maintenance.py
verify BACKUP_PATH. The backup requires the supported MySQL dump client.

For a database move, rehearse database_maintenance.py restore BACKUP_PATH
--confirm-empty-target against a NEW EMPTY database, with its DATABASE_URL
supplied privately in the environment. Never point a restore at the live Aiven
database. Compare schema/row counts and run application readiness/research
checks before switching. Check the script's --help for current options.

Copy any required approved model artifacts and document files separately;
a database dump does not back up Docker volumes. Keep image sources, dependency
lockfiles, the CA, privately stored secrets, and this runbook outside the trial.
Do a migration rehearsal before the placement deadline rather than relying on
post-expiry resource recovery.
