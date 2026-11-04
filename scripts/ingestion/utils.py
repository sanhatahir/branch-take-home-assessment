"""Reusable HTTP and atomic JSON persistence helpers."""

import json
import logging
import os
import tempfile
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

logger = logging.getLogger(__name__)
RETRYABLE_STATUSES = {408, 429, 500, 502, 503, 504}


def _retry_after_seconds(value):
    """Parse Retry-After delta-seconds or an HTTP date; ignore malformed values."""
    if value is None:
        return None
    value = value.strip()
    if value.isascii() and value.isdigit():
        return int(value)
    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return None


def fetch_json(url, params=None, timeout=30, *, max_retries=3, backoff_factor=1):
    """Fetch JSON with bounded retries for transient HTTP and network failures.

    max_retries counts retries after the initial request. Waits grow exponentially
    (backoff_factor * 2 ** retry_index), capped at 60 seconds, unless the server
    requests a longer wait via Retry-After. timeout applies to each request.
    Permanent HTTP errors, exhausted retries, and invalid JSON propagate to callers.
    """
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
        raise ValueError("max_retries must be a non-negative integer")
    if not isinstance(backoff_factor, (int, float)) or not 0 <= backoff_factor <= 60:
        raise ValueError("backoff_factor must be between 0 and 60 seconds")

    for attempt in range(max_retries + 1):
        retry_after = None
        try:
            response = requests.get(url, params=params, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout):
            if attempt == max_retries:
                raise
            reason = "connection failure or timeout"
        else:
            try:
                if response.status_code not in RETRYABLE_STATUSES or attempt == max_retries:
                    response.raise_for_status()
                    return response.json()
                reason = f"HTTP {response.status_code}"
                retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
            finally:
                response.close()

        delay = backoff_factor * 2 ** min(attempt, 6)
        delay = max(min(delay, 60), retry_after or 0)
        logger.warning(
            "Request failed (%s); retry %s/%s in %.1f seconds",
            reason, attempt + 1, max_retries, delay,
        )
        time.sleep(delay)


def save_json_atomic(data, output_path):
    """Replace a JSON snapshot only after writing successfully; clean up on failure."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(data, file, indent=2, ensure_ascii=False, allow_nan=False)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
