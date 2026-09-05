import tempfile
import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from migrate_cloud_mysql import migrate, secured_postgres_url


class CloudMySqlMigrationTests(unittest.TestCase):
    def test_source_url_requires_complete_postgresql_credentials(self):
        invalid = (
            "",
            "mysql://user:secret@example.com/db",
            "postgresql://user@example.com/db",
            "postgresql://user:CLICK_TO_REVEAL@example.com/db",
        )
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    secured_postgres_url(value)

    def test_source_url_requires_tls_without_exposing_credentials(self):
        secured = secured_postgres_url(
            "postgresql://user:s3cret@example.com/fintrack?sslmode=disable&application_name=fintrack"
        )
        self.assertIn("sslmode=require", secured)
        self.assertIn("application_name=fintrack", secured)
        self.assertNotIn("sslmode=disable", secured)

    @patch("migrate_cloud_mysql.write_cutover_manifest")
    @patch("migrate_cloud_mysql.migrate_legacy_to_mysql")
    @patch("migrate_cloud_mysql.verified_mysql_url")
    def test_migration_uses_empty_target_confirmation(
        self, verify_target, migrate_rows, write_manifest
    ):
        verify_target.return_value = "mysql://user:secret@mysql.example.com/db"
        migrate_rows.return_value = {
            "status": "verified",
            "credentialsIncluded": False,
        }
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "migration.json"
            write_manifest.return_value = manifest
            result = migrate(
                "postgresql://user:secret@postgres.example.com/db",
                "mysql://user:secret@mysql.example.com/db",
                Path(directory) / "ca.pem",
                manifest,
            )
        self.assertEqual("verified", result["status"])
        self.assertTrue(migrate_rows.call_args.kwargs["confirm_empty_target"])


if __name__ == "__main__":
    unittest.main()
