"""Independent recovery must not contact GCS for a verified mirrored model."""
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from artifact_storage import resolve_artifact


class MirrorTests(unittest.TestCase):
    def test_verified_mirror_does_not_need_google_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = b'test model bytes, not deserialized'
            digest = hashlib.sha256(data).hexdigest()
            expected = root / (digest + '.joblib')
            expected.write_bytes(data)
            with patch.dict(os.environ, {'MODEL_ARTIFACT_BUCKET': 'trusted',
                                         'MODEL_ARTIFACT_OFFLINE_ONLY': 'true'}):
                self.assertEqual(resolve_artifact('gs://trusted/models/model.joblib', root, digest), expected)

    def test_corrupt_mirror_fails_closed_without_downloading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            digest = 'a' * 64
            (root / (digest + '.joblib')).write_bytes(b'corrupted')
            with patch.dict(os.environ, {'MODEL_ARTIFACT_BUCKET': 'trusted',
                                         'MODEL_ARTIFACT_OFFLINE_ONLY': 'true'}):
                with self.assertRaisesRegex(ValueError, 'independent artifact mirror'):
                    resolve_artifact('gs://trusted/models/model.joblib', root, digest)

    def test_mirror_cannot_bypass_bucket_trust(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {'MODEL_ARTIFACT_BUCKET': 'trusted'}):
                with self.assertRaisesRegex(ValueError, 'trusted bucket'):
                    resolve_artifact('gs://other/models/model.joblib', Path(directory), 'a' * 64)


if __name__ == '__main__':
    unittest.main()
