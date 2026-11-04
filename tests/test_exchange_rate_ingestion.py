"""Focused regression check for an empty exchange-rate response."""

import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from scripts.ingestion import ingress_exchange_rates as ingestion


class EmptyExchangeRateResponseTest(unittest.TestCase):
    def test_empty_response_warns_and_preserves_existing_raw_files(self):
        start, end = date(2026, 10, 27), date(2026, 11, 2)
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            existing_file = output_dir / "rates_2026-11-02.json"
            original = b'[{"date":"2026-11-02","base":"USD","quote":"EUR","rate":0.9}]'
            existing_file.write_bytes(original)

            with patch.object(ingestion, "exchange_rate_output_dir", output_dir), \
                    patch.object(ingestion, "fetch_json", return_value=[]) as fetch, \
                    self.assertLogs(ingestion.logger, level="WARNING") as logs:
                result = ingestion.run_backfill(start, end)

            self.assertEqual(result, 0)
            fetch.assert_called_once_with(
                ingestion.exchange_rate_url,
                params={"base": "USD", "from": start.isoformat(), "to": end.isoformat()},
                timeout=60,
            )
            self.assertIn(str(start), logs.output[0])
            self.assertIn(str(end), logs.output[0])
            self.assertIn("existing raw data is preserved", logs.output[0])
            self.assertEqual(existing_file.read_bytes(), original)
            self.assertEqual(list(output_dir.iterdir()), [existing_file])


if __name__ == "__main__":
    unittest.main()
