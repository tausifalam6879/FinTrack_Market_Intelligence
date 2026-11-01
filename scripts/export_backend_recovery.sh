#!/usr/bin/env bash
# Run in the existing authorised Cloud Shell BEFORE the trial ends.
set -euo pipefail
umask 077
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RECOVERY_DIR="$(mktemp -d "${HOME}/fintrack-recovery.XXXXXX")"
trap 'printf "Recovery files retained privately at %s\n" "$RECOVERY_DIR"' EXIT
git -C "$REPO_ROOT" archive --format=tar HEAD -o "$RECOVERY_DIR/source.tar"
mkdir "$RECOVERY_DIR/artifacts"
gcloud storage rsync --recursive \
  "gs://fintrack-models-304232323336/models/" "$RECOVERY_DIR/artifacts/"
python3 - "$RECOVERY_DIR" <<'PY'
import hashlib, json, pathlib, sys, tarfile
root = pathlib.Path(sys.argv[1])
models = list((root / 'artifacts').rglob('*.joblib'))
if not models:
    raise SystemExit('No models downloaded: recovery package is incomplete.')
for model in models:
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    if model.name != digest + '.joblib':
        raise SystemExit('Model checksum/filename mismatch; package not created.')
    if model.parent != root / 'artifacts':
        raise SystemExit('Unexpected nested model directory; inspect before packaging.')
manifest = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in [root / 'source.tar', *models]}
(root / 'manifest.json').write_text(json.dumps(manifest, indent=2))
with tarfile.open(root / 'backend-recovery.tar.gz', 'w:gz') as archive:
    for name in ('source.tar', 'artifacts', 'manifest.json'):
        archive.add(root / name, arcname=name)
print('Verified models:', len(models))
print('Download this archive to your computer:', root / 'backend-recovery.tar.gz')
print('Contains source and model files. Database, credentials and schedules are separate.')
PY
printf '\nCloud Shell home is NOT the independent copy: download the archive now.\n'
