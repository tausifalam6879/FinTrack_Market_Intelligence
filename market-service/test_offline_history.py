import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from persistence import Database
import market_intelligence as market


class OfflineHistoryTests(unittest.TestCase):
    def test_history_uses_persisted_validated_bars_when_provider_is_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            database_url = f"sqlite:///{Path(directory) / 'offline.db'}"
            with patch.dict(os.environ, {"DATABASE_URL": database_url}, clear=False):
                repository = Database()
                repository.initialize_schema()
                repository.upsert_company({"symbol": "TEST.NS", "name": "Test", "source": "test", "metadata": {}})
                repository.upsert_market_bars([
                    {
                        "symbol": "TEST.NS",
                        "session_date": f"2026-08-{day:02d}",
                        "open": 100.0 + day,
                        "high": 102.0 + day,
                        "low": 99.0 + day,
                        "close": 101.0 + day,
                        "adjusted_close": 101.0 + day,
                        "volume": 1000.0 + day,
                        "source": "test",
                        "ingested_at": "2026-08-24T00:00:00+00:00",
                    }
                    for day in range(1, 11)
                ])
                market.clear_market_cache()
                with patch("market_intelligence.yf.Ticker") as ticker:
                    ticker.return_value.history.side_effect = OSError("network offline")
                    frame = market._history("TEST.NS", "5d")

        self.assertEqual(5, len(frame))
        self.assertEqual(111.0, float(frame.iloc[-1]["Close"]))
        self.assertIn("offline", frame.attrs["fintrack_source"])


if __name__ == "__main__":
    unittest.main()
