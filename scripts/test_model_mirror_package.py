import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from prepare_model_mirror import verified_models


class MirrorPackageTests(unittest.TestCase):
    def make_archive(self, directory, data=b'verified model', missing=False, symlink=False):
        digest = hashlib.sha256(b'verified model').hexdigest()
        name = 'artifacts/' + digest + '.joblib'
        path = Path(directory) / 'backup.tar.gz'
        with tarfile.open(path, 'w:gz') as archive:
            manifest = json.dumps({name: digest}).encode()
            member = tarfile.TarInfo('manifest.json'); member.size = len(manifest)
            archive.addfile(member, io.BytesIO(manifest))
            if not missing:
                member = tarfile.TarInfo(name)
                if symlink:
                    member.type = tarfile.SYMTYPE; member.linkname = '../../outside'
                    archive.addfile(member)
                else:
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
        return path

    def test_verifies_inventory_without_unpickling(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(1, len(verified_models(self.make_archive(directory))))

    def test_corruption_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                verified_models(self.make_archive(directory, data=b'corrupted'))

    def test_incomplete_backup_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, 'inventory'):
                verified_models(self.make_archive(directory, missing=True))

    def test_symlink_instead_of_model_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                verified_models(self.make_archive(directory, symlink=True))


if __name__ == '__main__':
    unittest.main()
