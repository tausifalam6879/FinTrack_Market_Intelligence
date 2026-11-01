# Backend continuity before Google Cloud trial expiry

## What is ready and what is not

The repository contains deployable source, a Render blueprint, an independent
Docker Compose deployment, an artifact export command and a configurable Pages
backend URL. These are recovery tools, not proof of a running standby server.
Do not switch public traffic until the alternate backend passes the checks below.

The Aiven database is shared application storage, not a second backend or proof
of a database backup. Keep a recent verified database export outside Google Cloud
as well as the source/model package below. Existing recovery rehearsal reports
only cover the backup used in those rehearsals.

## 1. Save models and source outside Google Cloud

Run in the authorised Cloud Shell, before the trial ends:

```bash
cd ~/FinTrack_Market_Intelligence
git pull --ff-only
bash scripts/export_backend_recovery.sh
```

Download the printed `backend-recovery.tar.gz` file using Cloud Shell's Download
file action. Store another private copy on independent storage. The package
contains tracked source and checksummed model files, not credentials or a database
export. Models may contain training metadata; keep the package private.
The export must be repeated after approving new models or changing code.

## 2. Configure independent hosting

For Render, `render.yaml` describes the Python API and Spring gateway. Configure
the real `DATABASE_URL` and Gemini key privately in Render. Upload Aiven's CA as
a secret file and use its Render path in the URL's `ssl-ca` query parameter.
Permit the selected Render region's documented outbound IP ranges in Aiven's
allowlist; retain the current Google NAT entry until migration is verified.
Do not disable TLS or open all database IPs just to make migration work.

Render Free services have ephemeral storage. An uploaded model cache cannot be
relied on across restarts. A persistent disk or private deployment image containing
the verified mirror is required for approved-model continuity independent of GCS.
Keeping both free services awake also consumes their shared monthly allowance.
Do not assume a monitoring ping removes those limits.

For an independent server/VM, extract `source.tar` into the application directory
and copy the package's `artifacts/` into `backups/recovery/artifacts/`. Verify each
file against `manifest.json` before use. Put Aiven's CA at `secrets/aiven-ca.pem`.
Create a private `.env.recovery` (never commit it) with:

```dotenv
DATABASE_URL=mysql://USER:ENCODED_PASSWORD@HOST:PORT/DATABASE?ssl-mode=verify_identity&ssl-ca=/etc/secrets/ca.pem
LLM_PROVIDER=gemini
GEMINI_API_KEY=SET_PRIVATELY
```

The host's outbound address must be allowed by Aiven. The server must have enough
RAM for Java and Python. From the source directory run:

```bash
docker compose -f compose.recovery.yaml up -d --build
```

Expose the gateway through an HTTPS reverse proxy. The compose ports bind only
to localhost. Ensure UID 10001 can read the mirrored model files and certificate;
keep `.env.recovery` readable only by the deployment administrator. The mirror
uses existing GCS paths in database records but loads checksummed local files
before requesting Google credentials. Offline mode never downloads from GCS.

## 3. Verify before switching

```bash
python3 scripts/check_research_response.py https://ALTERNATE_GATEWAY
python3 scripts/check_agent_speed.py https://ALTERNATE_GATEWAY
```

Also verify a known approved model reports `approved_artifact`, report answers
retain source citations, and news/MLOps pages load in a real browser. Restart the
alternate services and repeat the approved-model check with GCS credentials
absent. Test Aiven connectivity and Gemini from the alternate host itself.

## 4. Switch the public website

In GitHub repository Settings > Secrets and variables > Actions > Variables set
`FINTRACK_PUBLIC_API_URL` to the verified alternate HTTPS gateway URL. Run the
`Deploy frontend to GitHub Pages` workflow manually. Test company research, AI,
news and MLOps on the public website. Change the variable back and rebuild to
roll back. The default remains the current Cloud Run gateway until this step.

This is an explicit cutover, not automatic production failover. Cached browser
responses do not prove the alternate server is running.

## 5. Remaining Google dependencies

Cloud Scheduler, ingestion/monitoring jobs, training/preparation jobs, SQL backup
jobs, Secret Manager, GCS model files and Gemini project quotas must be checked
separately. The compose deployment intentionally disables preparation enqueueing
until a worker on the new host is configured. It does not migrate schedules or
approve models. A working serving backend does not imply these jobs moved.

Monitoring may check a lightweight health endpoint every five minutes once a
service is live. It helps detect outages; it cannot extend trial credits, restore
a suspended account or guarantee continuous availability on free hosting.
