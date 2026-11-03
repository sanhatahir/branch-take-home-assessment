"""Reusable HTTP and atomic JSON persistence helpers."""

import json
import os
import tempfile
from pathlib import Path

import requests


def fetch_json(url, params=None, timeout=30):
    """Fetch JSON, propagating HTTP, connection, timeout, and parsing errors."""
    response = requests.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


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
