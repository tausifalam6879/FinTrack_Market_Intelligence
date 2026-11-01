# Independent approved-model image

Status: packaging tools are available. This is not a deployed model mirror.
The downloaded real archive, private registry access and offline inference
verification are required before calling this complete.

## Prepare locally

Use the downloaded recovery archive; the script verifies its model inventory and
hashes without extracting its old source tree or unpickling the models. Output
must be a new folder inside the Git-ignored `backups/` directory.

```powershell
.\market-service\.venv\Scripts\python.exe scripts/prepare_model_mirror.py --archive 'FULL_PATH_TO_BACKUP.tar.gz'
docker build --platform linux/amd64 -t fintrack-market-base:recovery market-service
docker build --platform linux/amd64 -t fintrack-market-mirror:recovery backups/render-model-image
```

The second image includes verified models, the current application code and
`MODEL_ARTIFACT_OFFLINE_ONLY=true`. It does not contain Aiven/Gemini credentials.
These files remain present across container restarts because they are image
contents. This does not require a persistent disk.

Before publishing, test the image with networking disabled: verify all file
checksums, then load and perform inference for the models currently approved in
the database. Merely including all 44 files does not approve candidates or prove
that the archive includes every model approved since its export date. Retain the
artifact SHA256, model-run ID and dataset identity checks in `model_registry.py`.

## Publish and attach to Render

Use a confirmed **private** repository in Docker Hub or GHCR, independent of the
expiring Google Cloud project. Verify repository visibility before any push.
No push is performed by the packaging script. Never add `backups/`, model files,
database URLs or registry tokens to the public Git repository.

Render supports private image-backed services using registry pull credentials:
https://render.com/docs/deploying-an-image

If a separate image-backed API service is necessary, preserve the current Render
gateway URL. Configure Aiven TLS, the existing restricted database network access
and Gemini privately on the new API. Test it before pointing the gateway upstream
to it. Keep the old API available for rollback until verification succeeds.
All free instances still share the workspace allowance; this does not remove
Render's sleep or running-hour limits.

## Acceptance checks

1. No Google service-account credentials are supplied to the model image.
2. Approved symbols use `approved_artifact`, with matching run IDs, on Render.
3. A restart still loads those approved models successfully.
4. A missing/corrupt model fails validation and is never silently approved.
5. Google remains the frontend's primary backend.
6. For companies without an approved model, existing experimental/missing-data
   behavior remains clearly labelled.

Image-backed Render services need a new image build and deployment when code or
model files change. A Git push by itself does not update a prebuilt image.
