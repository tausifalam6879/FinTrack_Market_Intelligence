# Production MySQL handoff

FinTrack uses MySQL when `DATABASE_URL` begins with `mysql://` or
`mysql+pymysql://`. Configure the private URL in the hosted API without
committing it to Git.

## Local setup

The Windows installer runs `configure-local-mysql.ps1` when a FinTrack MySQL
account has not been configured. The script asks for the MySQL administrator
password once, creates the `fintrack` and `fintrack_mlflow` databases, generates
a separate application password and stores only the application settings for
the current Windows user. It never prints or commits either password.

## Hosted configuration

Choose a managed MySQL provider and create an empty database before changing
the running service. Do not put the connection string in Git.

```env
DATABASE_URL=mysql://USER:PASSWORD@HOST:3306/fintrack?ssl-mode=REQUIRED
REQUIRE_DURABLE_DATABASE=true
DATABASE_BACKUP_POLICY=provider-pitr-plus-verified-logical-export
```

TLS-enabled application connections verify the server certificate. If the
provider uses a private certificate authority, add `ssl-ca=/path/to/ca.pem`
to the URL and supply that CA file through the hosting provider's secret-file
settings.

After migration and backup verification, `prepare-render-mysql-cutover.ps1`
copies the CA contents and a Render-ready URL to the Windows clipboard one at
a time. The URL requires hostname-verified TLS and reads the CA from the Render
secret file `/etc/secrets/ca.pem`. The script clears the clipboard after the
operator confirms that the setting was saved.

For a Windows connection check, download the provider CA as `Downloads/ca.pem`
and open `Check cloud MySQL.cmd`. Paste the complete Aiven Service URI into
the hidden prompt. The checker performs only read-only queries and requires
verified TLS. After a successful check it saves the URI using Windows
credential encryption under the Git-ignored `backups/cloud-mysql/` directory,
along with a certificate copy and a non-secret connection report. It does not
change the local MySQL settings or the Render configuration, and does not
copy application data. Keep the private setup files out of Git and chat.

## Safe cutover checklist

1. Create an empty MySQL database close to the hosted API region.
2. Pause scheduled writes to the previous database.
3. Take and verify a backup of the previous database.
4. Install `requirements-migration.txt` only in the trusted migration environment.
5. Set `SOURCE_DATABASE_URL` to the previous connection string and
   `DATABASE_URL` to the new MySQL connection string.
6. Run the verified migration while the MySQL target is empty.
7. Confirm that every allowlisted table has matching row counts and SHA-256 evidence.
8. Configure the hosted API secret and deploy only after local and CI tests pass.
9. Verify `/health/ready` reports `mysql`, schema version `5/5`, and durable storage.
10. Keep `FINTRACK_DATABASE_URL` unset in GitHub Actions unless the database
    allowlist includes a controlled, fixed-egress runner and the private CA is
    installed on that runner. Do not open Aiven to every IP merely to run a
    schedule.

```powershell
cd market-service
$env:SOURCE_DATABASE_URL = "<previous database connection URL>"
$env:DATABASE_URL = "mysql://USER:PASSWORD@HOST:3306/fintrack?ssl-mode=REQUIRED"
python database_maintenance.py migrate --confirm-empty-target --manifest-path ../backups/mysql-cutover.json
```

The migration refuses a non-empty target or a run without explicit
confirmation. Application rows are copied in foreign-key-safe order and read
back before the transaction commits. The verification manifest contains row
counts and hashes, never credentials.

## Backup and restore

`database_maintenance.py backup` uses `mysqldump` with a consistent transaction
and generates a checksum manifest. Restore requires `--confirm-empty-target`
and refuses a database that already contains project tables. Always test a
restore against a separate empty MySQL database.
