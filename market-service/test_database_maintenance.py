import tempfile
import unittest
from pathlib import Path
import sqlite3

from database_maintenance import (
    _mysql_environment,
    create_backup,
    restore_empty_target,
    verify_backup,
)
from persistence import Database, LATEST_SCHEMA_VERSION


class DatabaseMaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source = Database(f"sqlite:///{self.root / 'source.db'}")
        self.source.initialize_schema()
        self.source.upsert_company({
            "symbol": "SAFE.NS", "name": "Safe Limited", "source": "test"
        })

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_schema_migrations_are_versioned_and_idempotent(self):
        first = self.source.schema_status()
        self.source.initialize_schema()
        second = self.source.schema_status()

        self.assertEqual(LATEST_SCHEMA_VERSION, first["currentVersion"])
        self.assertTrue(first["upToDate"])
        self.assertEqual(first["appliedMigrations"], second["appliedMigrations"])

    def test_legacy_unversioned_tables_are_adopted_without_data_loss(self):
        legacy_path = self.root / "legacy.db"
        connection = sqlite3.connect(legacy_path)
        connection.execute("""
            CREATE TABLE companies (
                symbol TEXT PRIMARY KEY, name TEXT NOT NULL, exchange TEXT, sector TEXT,
                industry TEXT, region TEXT, currency TEXT, source TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
            )
        """)
        connection.execute(
            "INSERT INTO companies (symbol, name, source, updated_at) VALUES (?, ?, ?, ?)",
            ("LEGACY.NS", "Legacy Limited", "test", "2026-01-01T00:00:00+00:00"),
        )
        connection.commit()
        connection.close()

        legacy = Database(f"sqlite:///{legacy_path}")
        legacy.initialize_schema()

        self.assertTrue(legacy.schema_status()["upToDate"])
        with legacy.connect() as migrated:
            cursor = migrated.cursor()
            cursor.execute("SELECT name FROM companies WHERE symbol = ?", ("LEGACY.NS",))
            self.assertEqual("Legacy Limited", cursor.fetchone()[0])

    def test_sqlite_backup_is_checksummed_and_restores_only_to_empty_target(self):
        backup = self.root / "fintrack-test.sqlite3"
        created = create_backup(backup, self.source)
        verified = verify_backup(backup)
        target = Database(f"sqlite:///{self.root / 'restored.db'}")

        restored = restore_empty_target(backup, target, confirm_empty_target=True)

        self.assertEqual("verified", verified["status"])
        self.assertEqual(64, len(created["sha256"]))
        self.assertEqual(LATEST_SCHEMA_VERSION, restored["schema"]["currentVersion"])
        with target.connect() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT name FROM companies WHERE symbol = ?", ("SAFE.NS",))
            self.assertEqual("Safe Limited", cursor.fetchone()[0])

    def test_restore_refuses_non_empty_database(self):
        backup = self.root / "fintrack-refusal.sqlite3"
        create_backup(backup, self.source)

        with self.assertRaises(ValueError):
            restore_empty_target(backup, self.source, confirm_empty_target=True)

    def test_mysql_backup_arguments_include_tls_ca(self):
        environment, arguments, database_name = _mysql_environment(
            "mysql://user:secret@example.com:13837/defaultdb"
            "?ssl-mode=VERIFY_IDENTITY&ssl-ca=C%3A%5Csecure%5Cca.pem"
        )

        self.assertEqual("defaultdb", database_name)
        self.assertEqual("secret", environment["MYSQL_PWD"])
        self.assertIn("--ssl-mode", arguments)
        self.assertIn("VERIFY_IDENTITY", arguments)
        self.assertIn("--ssl-ca", arguments)
        self.assertIn(r"C:\secure\ca.pem", arguments)


if __name__ == "__main__":
    unittest.main()
