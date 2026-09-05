import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from database_cutover import migrate_legacy_to_mysql, write_cutover_manifest
from persistence import Database


class DatabaseCutoverTests(unittest.TestCase):
    def _database(self, root: Path, name: str) -> Database:
        database = Database(f"sqlite:///{root / name}")
        database.initialize_schema()
        return database

    def _seed_source(self, database: Database) -> None:
        database.upsert_company({
            "symbol": "RELIANCE.NS",
            "name": "Reliance Industries Limited",
            "exchange": "NSE",
            "region": "India",
            "currency": "INR",
            "source": "test",
            "metadata": {"fixture": True},
        })
        database.upsert_market_bars([{
            "symbol": "RELIANCE.NS",
            "session_date": "2026-08-12",
            "open": 1400.0,
            "high": 1425.0,
            "low": 1395.0,
            "close": 1418.0,
            "adjusted_close": 1418.0,
            "volume": 1000000,
            "source": "test",
            "ingested_at": "2026-08-13T00:00:00+00:00",
        }])

    def test_atomic_copy_verifies_every_allowlisted_table(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._database(root, "source.db")
            target = self._database(root, "target.db")
            self._seed_source(source)

            result = migrate_legacy_to_mysql(
                source,
                target,
                confirm_empty_target=True,
                batch_size=1,
                allow_legacy_target_for_tests=True,
            )

            self.assertEqual("verified", result["status"])
            self.assertEqual(10, result["tablesVerified"])
            self.assertEqual(2, result["totalRows"])
            self.assertEqual(1, result["tables"]["companies"]["rowCount"])
            self.assertEqual(1, result["tables"]["market_bars"]["rowCount"])
            self.assertTrue(all(table["verified"] for table in result["tables"].values()))
            with target.connect() as connection:
                cursor = connection.cursor()
                cursor.execute("SELECT name FROM companies WHERE symbol = ?", ("RELIANCE.NS",))
                migrated_name = cursor.fetchone()[0]
            self.assertEqual("Reliance Industries Limited", migrated_name)

    def test_migration_requires_confirmation_and_an_empty_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._database(root, "source.db")
            target = self._database(root, "target.db")
            self._seed_source(source)

            with self.assertRaisesRegex(ValueError, "confirm-empty-target"):
                migrate_legacy_to_mysql(
                    source, target, allow_legacy_target_for_tests=True
                )

            target.upsert_company({
                "symbol": "EXISTING.NS", "name": "Existing", "source": "test"
            })
            with self.assertRaisesRegex(ValueError, "will not be overwritten"):
                migrate_legacy_to_mysql(
                    source,
                    target,
                    confirm_empty_target=True,
                    allow_legacy_target_for_tests=True,
                )

    def test_manifest_contains_evidence_but_no_database_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._database(root, "source.db")
            target = self._database(root, "target.db")
            self._seed_source(source)
            result = migrate_legacy_to_mysql(
                source,
                target,
                confirm_empty_target=True,
                allow_legacy_target_for_tests=True,
            )
            manifest_path = write_cutover_manifest(result, root / "cutover.json")
            serialized = manifest_path.read_text(encoding="utf-8")

            self.assertFalse(json.loads(serialized)["credentialsIncluded"])
            self.assertNotIn("DATABASE_URL", serialized)
            self.assertNotIn("password", serialized.lower())
            with self.assertRaisesRegex(ValueError, "already exists"):
                write_cutover_manifest(result, manifest_path)

    def test_source_schema_is_not_modified_during_migration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._database(root, "source.db")
            target = self._database(root, "target.db")
            self._seed_source(source)
            source.initialize_schema = Mock(
                side_effect=AssertionError("source schema must remain untouched")
            )

            result = migrate_legacy_to_mysql(
                source,
                target,
                confirm_empty_target=True,
                allow_legacy_target_for_tests=True,
            )

            self.assertEqual("verified", result["status"])
            source.initialize_schema.assert_not_called()


if __name__ == "__main__":
    unittest.main()
