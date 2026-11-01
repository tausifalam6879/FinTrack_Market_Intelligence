import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

from persistence import Database
import market_intelligence as market


class PeerSnapshotTests(unittest.TestCase):
    def test_retained_evidence_survives_company_history_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database('sqlite:///' + str(Path(directory) / 'test.db'))
            self.check_roundtrip(db, 'NEWCO')

    @unittest.skipUnless(os.getenv('FINTRACK_TEST_MYSQL_URL'), 'Dedicated test MySQL not configured')
    def test_real_mysql_retains_evidence_during_upsert(self):
        self.check_roundtrip(Database(os.environ['FINTRACK_TEST_MYSQL_URL']), 'PEER_SNAPSHOT_TEST')

    def check_roundtrip(self, db, symbol):
        db.initialize_schema()
        db.upsert_company({'symbol': symbol, 'name': 'Company', 'metadata': {'original': True}})
        snapshot = {'status': 'available', 'symbol': symbol, 'sector': 'Technology', 'region': 'US',
                    'generatedAt': datetime.now(timezone.utc).isoformat(), 'peers': [{'symbol': 'OTHER'}]}
        db.store_peer_snapshot(symbol, snapshot)
        self.assertEqual(snapshot, db.load_peer_snapshot(symbol))
        db.upsert_company({'symbol': symbol, 'name': 'Updated', 'metadata': {'latest': True}})
        self.assertEqual(snapshot, db.load_peer_snapshot(symbol))
        self.assertIsNone(db.load_peer_snapshot('NONEXISTENT'))
        with self.assertRaises(ValueError):
            db.store_peer_snapshot('WRONG', snapshot)

    def test_snapshot_is_scoped_and_expires_in_twenty_four_hours(self):
        snapshot = {'status': 'available', 'symbol': 'AAPL', 'sector': 'Technology', 'region': 'US',
                    'generatedAt': datetime.now(timezone.utc).isoformat(), 'peers': []}
        db = Mock()
        db.load_peer_snapshot.return_value = snapshot
        with patch.object(market, 'Database', return_value=db):
            result = market._stored_sector_peers('AAPL', 'Technology', 'us')
            self.assertEqual('stored_provider_snapshot', result['discoveryMode'])
            self.assertIn('not live', result['coverageNotice'])
            self.assertEqual({}, market._stored_sector_peers('AAPL', 'Healthcare', 'us'))
            self.assertEqual({}, market._stored_sector_peers('AAPL', 'Technology', 'in'))
            self.assertEqual({}, market._stored_sector_peers('OTHER', 'Technology', 'us'))
            snapshot['generatedAt'] = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
            self.assertEqual({}, market._stored_sector_peers('AAPL', 'Technology', 'us'))


if __name__ == '__main__':
    unittest.main()
