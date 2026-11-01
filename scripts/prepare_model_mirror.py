"""Prepare a private model-image context without extracting executable archive content."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile

ROOT = Path(__file__).resolve().parents[1]
MAX_MODEL_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024


def verified_models(archive_path):
    with tarfile.open(archive_path, 'r:*') as archive:
        members = archive.getmembers()
        names = [m.name for m in members]
        if len(names) != len(set(names)):
            raise ValueError('Duplicate archive entries are not accepted.')
        manifest_member = archive.getmember('manifest.json')
        if not manifest_member.isfile() or manifest_member.size > 1024 * 1024:
            raise ValueError('Invalid recovery manifest.')
        manifest = json.load(archive.extractfile(manifest_member))
        if not isinstance(manifest, dict):
            raise ValueError('Invalid recovery manifest object.')
        expected = {name: digest for name, digest in manifest.items() if name.startswith('artifacts/')}
        actual = {m.name for m in members if m.isfile() and m.name.startswith('artifacts/')}
        if not expected or set(expected) != actual:
            raise ValueError('Model inventory differs from the recovery manifest.')
        total = 0
        result = {}
        for name, checksum in expected.items():
            path = PurePosixPath(name)
            if len(path.parts) != 2 or not isinstance(checksum, str) or not re.fullmatch(r'[0-9a-f]{64}', checksum):
                raise ValueError('Invalid model path or checksum.')
            if path.name != checksum + '.joblib':
                raise ValueError('Model filename must equal its SHA256 checksum.')
            member = archive.getmember(name)
            total += member.size
            if not member.isfile() or member.size > MAX_MODEL_BYTES or total > MAX_TOTAL_BYTES:
                raise ValueError('Invalid model member or size limit exceeded.')
            data = archive.extractfile(member).read()
            if hashlib.sha256(data).hexdigest() != checksum:
                raise ValueError('Model content checksum mismatch.')
            result[path.name] = data
        # This stage never unpickles a model or extracts source.tar.
        return result


def prepare(archive_path, output):
    models = verified_models(archive_path)
    output = Path(output).resolve()
    private_root = (ROOT / 'backups').resolve()
    if not output.is_relative_to(private_root) or output == private_root:
        raise ValueError('Output must be a NEW subdirectory inside the ignored backups directory.')
    output.mkdir(parents=True, exist_ok=False)
    model_dir = output / 'models'
    model_dir.mkdir()
    for name, data in models.items():
        (model_dir / name).write_bytes(data)
    shutil.copyfile(ROOT / 'market-service' / 'Dockerfile.mirror', output / 'Dockerfile')
    (output / 'inventory.json').write_text(json.dumps({
        'modelCount': len(models),
        'sha256': {name: hashlib.sha256(data).hexdigest() for name, data in models.items()},
        'privateImageRequired': True,
        'databaseCredentialsIncluded': False,
    }, indent=2), encoding='utf-8')
    return {'status': 'private_context_ready', 'modelCount': len(models), 'directory': str(output)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'backups' / 'render-model-image')
    args = parser.parse_args()
    print(json.dumps(prepare(args.archive, args.output), indent=2))


if __name__ == '__main__':
    main()
