"""Durable, immutable GCS artifacts with a verified local download cache."""
import hashlib
import os
from pathlib import Path
from tempfile import NamedTemporaryFile


def resolve_artifact(value, root, checksum):
    if not str(value).startswith("gs://"):
        return Path(value).resolve()
    bucket, separator, key = str(value)[5:].partition("/")
    trusted_bucket = os.getenv("MODEL_ARTIFACT_BUCKET", "")
    prefix = os.getenv("MODEL_ARTIFACT_PREFIX", "models/").strip("/") + "/"
    if not trusted_bucket or bucket != trusted_bucket or not separator or not key.startswith(prefix):
        raise ValueError("Artifact is outside the configured trusted bucket/prefix.")
    if not key.endswith(".joblib") or len(checksum) != 64 or any(c not in "0123456789abcdef" for c in checksum):
        raise ValueError("Invalid artifact extension or checksum.")
    from google.cloud import storage
    root.mkdir(parents=True, exist_ok=True)
    target = root / (checksum + ".joblib")
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == checksum:
        return target
    with NamedTemporaryFile(dir=root, delete=False) as stream:
        temporary = Path(stream.name)
    try:
        blob = storage.Client().bucket(bucket).blob(key)
        if blob.size is None:
            blob.reload(timeout=30)
        if blob.size > 100 * 1024 * 1024:
            raise ValueError("Artifact exceeds 100 MiB download limit.")
        blob.download_to_filename(str(temporary), timeout=60)
        if hashlib.sha256(temporary.read_bytes()).hexdigest() != checksum:
            raise ValueError("Downloaded artifact checksum mismatch.")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def publish_artifact(path, checksum):
    bucket = os.getenv("MODEL_ARTIFACT_BUCKET")
    if not bucket:
        return str(path.resolve())
    from google.cloud import storage
    prefix = os.getenv("MODEL_ARTIFACT_PREFIX", "models/").strip("/")
    key = f"{prefix}/{checksum}.joblib"
    storage.Client().bucket(bucket).blob(key).upload_from_filename(
        str(path), if_generation_match=0, timeout=60
    )
    return f"gs://{bucket}/{key}"
