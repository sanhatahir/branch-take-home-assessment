"""HTTP retry behavior without network calls or real sleeps."""

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, call, patch

import requests

from scripts.ingestion import utils


def response(status=200, headers=None, payload=None):
    result = Mock(status_code=status, headers=headers or {})
    result.json.return_value = payload
    if status >= 400:
        result.raise_for_status.side_effect = requests.HTTPError(response=result)
    return result


class FetchJsonTests(unittest.TestCase):
    def setUp(self):
        self.get = patch.object(utils.requests, "get").start()
        self.sleep = patch.object(utils.time, "sleep").start()
        self.addCleanup(patch.stopall)

    def test_success_preserves_arguments_and_closes_response(self):
        result = response(payload={"ok": True})
        self.get.return_value = result
        self.assertEqual(utils.fetch_json("https://example.test", {"page": 2}, 10), {"ok": True})
        self.get.assert_called_once_with("https://example.test", params={"page": 2}, timeout=10)
        result.close.assert_called_once()
        self.sleep.assert_not_called()

    def test_transient_statuses_retry_with_exponential_backoff(self):
        for status in utils.RETRYABLE_STATUSES:
            with self.subTest(status=status):
                self.sleep.reset_mock()
                self.get.side_effect = [response(status), response(status), response(payload=[])]
                self.assertEqual(utils.fetch_json("url"), [])
                self.assertEqual(self.sleep.call_args_list, [call(1), call(2)])

    def test_retry_after_seconds_and_malformed_fallback(self):
        self.get.side_effect = [
            response(429, {"Retry-After": "120"}),
            response(503, {"Retry-After": "invalid"}),
            response(payload={}),
        ]
        self.assertEqual(utils.fetch_json("url"), {})
        self.assertEqual(self.sleep.call_args_list, [call(120), call(2)])

    def test_retry_after_http_date_and_past_date(self):
        with patch.object(utils, "datetime") as clock:
            clock.now.return_value = datetime(2026, 1, 1, tzinfo=timezone.utc)
            self.assertEqual(utils._retry_after_seconds("Thu, 01 Jan 2026 00:00:10 GMT"), 10)
            self.assertEqual(utils._retry_after_seconds("Wed, 31 Dec 2025 23:59:00 GMT"), 0)

    def test_network_failures_retry(self):
        self.get.side_effect = [requests.Timeout(), requests.ConnectionError(), response(payload=42)]
        self.assertEqual(utils.fetch_json("url"), 42)
        self.assertEqual(self.sleep.call_args_list, [call(1), call(2)])

    def test_exhaustion_raises_last_http_error(self):
        result = response(503)
        self.get.return_value = result
        with self.assertRaises(requests.HTTPError) as caught:
            utils.fetch_json("url", max_retries=2)
        self.assertIs(caught.exception.response, result)
        self.assertEqual(self.get.call_count, 3)
        self.assertEqual(self.sleep.call_count, 2)

    def test_no_retries_raises_network_failure_immediately(self):
        self.get.side_effect = requests.Timeout()
        with self.assertRaises(requests.Timeout):
            utils.fetch_json("url", max_retries=0)
        self.get.assert_called_once()
        self.sleep.assert_not_called()

    def test_permanent_errors_and_invalid_json_do_not_retry(self):
        for status in (400, 401, 403, 404):
            with self.subTest(status=status):
                self.get.return_value = response(status)
                with self.assertRaises(requests.HTTPError):
                    utils.fetch_json("url")
        self.get.return_value = response()
        self.get.return_value.json.side_effect = requests.exceptions.JSONDecodeError("Invalid", "x", 0)
        with self.assertRaises(requests.exceptions.JSONDecodeError):
            utils.fetch_json("url")
        self.sleep.assert_not_called()

    def test_invalid_retry_settings_fail_before_request(self):
        for options in ({"max_retries": -1}, {"max_retries": 1.5}, {"backoff_factor": -1}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                utils.fetch_json("url", **options)
        self.get.assert_not_called()
