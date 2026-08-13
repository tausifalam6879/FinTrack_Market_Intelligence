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
```

If the database belongs to the same Blueprint, define it in the top-level `databases` list only after choosing its region and paid/free lifecycle. Render documents `fromDatabase` in the [Blueprint specification](https://render.com/docs/blueprint-spec).

## Deployment checklist

1. Create an empty PostgreSQL database in the same region as the Render API.
2. Set the API's `DATABASE_URL` secret. Do not put its value in Git.
3. Deploy once and verify `/health/ready` reports `postgresql`, schema version `4/4`, and `durableAcrossDeploys: true`.
4. Store the external connection URL as the GitHub secret `FINTRACK_DATABASE_URL`.
5. Run **Scheduled market data operations** manually once and inspect its non-sensitive report artifact.
6. Configure provider point-in-time recovery where available and create periodic logical exports with `database_maintenance.py backup` or provider tooling.
7. Test restore against a separate empty database. Never test restore against the live database.

## Migration and backup behavior

- Startup applies idempotent, numbered migrations in one database transaction.
- `schema_migrations` records version, name and UTC application time.
- Readiness fails when the connected schema is behind the application version.
- SQLite development backups use its online backup API.
- PostgreSQL backups use `pg_dump` custom format without ownership or credentials in the output manifest.
- Restore requires `--confirm-empty-target` and refuses any database that already contains project tables.
