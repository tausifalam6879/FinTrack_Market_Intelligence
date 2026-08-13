# Production PostgreSQL handoff

FinTrack automatically uses PostgreSQL when `DATABASE_URL` begins with `postgresql://` or `postgres://`. The same URL must be configured in the Render API and stored as the GitHub repository secret `FINTRACK_DATABASE_URL` so scheduled operations update the database that the public API reads.

## Do not silently provision the free database

Render's [free-instance documentation](https://render.com/docs/free) states that Free Render Postgres expires after 30 days and does not provide managed backups. It is useful for a short interview demo, not long-term persistence. Paid Render Postgres provides recovery features documented in [Render Postgres backups](https://render.com/docs/postgresql-backups). An external managed PostgreSQL provider is also supported.

Creating or upgrading a database can incur charges, so the active `render.yaml` deliberately does not create one. Choose the provider and plan first.

## Render Blueprint connection snippet

After deliberately creating a database named `fintrack-market-db`, the API can reference it without committing credentials:

```yaml
services:
  - type: web
    name: fintrack-market-intelligence-api
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: fintrack-market-db
          property: connectionString
      - key: DATABASE_BACKUP_POLICY
        value: provider-pitr-plus-logical-export
      - key: REQUIRE_DURABLE_DATABASE
        value: "true"
```

If the database belongs to the same Blueprint, define it in the top-level `databases` list only after choosing its region and paid/free lifecycle. Render documents `fromDatabase` in the [Blueprint specification](https://render.com/docs/blueprint-spec).

## Deployment checklist

1. Create an empty PostgreSQL database in the same region as the Render API.
2. Stop writes to the current SQLite database and create a verified online backup.
3. Run the verified cutover command below while the PostgreSQL target is still empty.
4. Set the Render API's `DATABASE_URL` secret. Do not put its value in Git.
5. Set `REQUIRE_DURABLE_DATABASE=true` and an accurate `DATABASE_BACKUP_POLICY` only after PostgreSQL is connected.
6. Deploy once and verify `/health/ready` reports `postgresql`, schema version `4/4`, `durableAcrossDeploys: true`, and `durabilityRequired: true`.
7. Store the same external connection URL as the GitHub secret `FINTRACK_DATABASE_URL`.
8. Run **Scheduled market data operations** manually once and inspect its non-sensitive report artifact.
9. Configure provider point-in-time recovery where available and create periodic logical exports with `database_maintenance.py backup` or provider tooling.
10. Test restore against a separate empty database. Never test restore against the live database.

## Verified SQLite-to-PostgreSQL cutover

Run these commands from `market-service`. Environment variables keep the PostgreSQL credential out of shell history and the generated manifest:

```powershell
$env:SOURCE_DATABASE_URL = "sqlite:///C:/absolute/path/to/fintrack.db"
$env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST:5432/DATABASE?sslmode=require"
python database_maintenance.py migrate --confirm-empty-target --manifest-path ../backups/postgres-cutover.json
```

The command refuses a missing SQLite source, a non-PostgreSQL destination, an already-populated target, or a run without explicit confirmation. It copies only the ten allowlisted application tables in foreign-key-safe order inside one target transaction. Every table is read back and compared using its row count and deterministic SHA-256 digest. The manifest contains this verification evidence but no database URL or credentials.

If migration fails, target application rows are rolled back. Keep the SQLite database and its verified backup unchanged until the new deployment passes readiness and a representative market analysis works. Rollback means restoring the previous Render `DATABASE_URL`/guard settings and redeploying; do not try to merge writes made independently to both databases.

## Migration and backup behavior

- Startup applies idempotent, numbered migrations in one database transaction.
- `schema_migrations` records version, name and UTC application time.
- Readiness fails when the connected schema is behind the application version.
- When `REQUIRE_DURABLE_DATABASE=true`, readiness also fails if configuration falls back to SQLite.
- SQLite development backups use its online backup API.
- PostgreSQL backups use `pg_dump` custom format without ownership or credentials in the output manifest.
- Restore requires `--confirm-empty-target` and refuses any database that already contains project tables.
