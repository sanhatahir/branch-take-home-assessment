"""CLI orchestration checks without network calls or the local warehouse."""

import json
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock

import pytest

from scripts import build_daily as build
from scripts.ingestion import ingress_exchange_rates as ingestion
from scripts.transformations.transform_exchange_rates import transform_exchange_rates


@pytest.fixture
def steps(monkeypatch):
    names = ["ingest_countries", "ingest_exchange_rate_window", "ingest_exchange_rate_daily",
             "transform_countries", "transform_exchange_rates", "create_reporting_view"]
    mocks = {name: Mock(return_value=1) for name in names}
    for name, operation in mocks.items():
        monkeypatch.setattr(build, name, operation)
    return mocks


def test_default_window(steps):
    today = date.today()
    assert build.main([]) == 0
    steps["ingest_exchange_rate_window"].assert_called_once_with(today - timedelta(days=6), today)
    steps["ingest_exchange_rate_daily"].assert_not_called()
    for name in ("ingest_countries", "transform_countries", "transform_exchange_rates", "create_reporting_view"):
        steps[name].assert_called_once_with()


def test_dated_pipeline_order(steps):
    calls = Mock()
    for name, operation in steps.items():
        calls.attach_mock(operation, name)
    assert build.main(["--date", "2026-01-15"]) == 0
    steps["ingest_exchange_rate_daily"].assert_called_once_with(date(2026, 1, 15))
    assert [call[0] for call in calls.mock_calls] == [
        "ingest_countries", "ingest_exchange_rate_daily", "transform_countries",
        "transform_exchange_rates", "create_reporting_view",
    ]


@pytest.mark.parametrize("value", ["bad", "2026-02-30", "20260115", "2026-W03-4",
                                      (date.today() + timedelta(days=1)).isoformat()])
def test_invalid_dates_fail_before_any_step(steps, value):
    with pytest.raises(SystemExit) as error:
        build.main(["--date", value])
    assert error.value.code == 2
    for operation in steps.values():
        operation.assert_not_called()


@pytest.mark.parametrize("failed,skipped", [
    ("ingest_exchange_rate_daily", ["transform_exchange_rates", "create_reporting_view"]),
    ("ingest_countries", ["transform_countries", "create_reporting_view"]),
])
def test_ingestion_failure_checks_dependencies(steps, caplog, failed, skipped):
    steps[failed].side_effect = RuntimeError("ingestion failed")
    assert build.main(["--date", "2026-01-15"]) == 1
    for name in skipped:
        steps[name].assert_not_called()
    independent = "transform_countries" if failed == "ingest_exchange_rate_daily" else "transform_exchange_rates"
    steps[independent].assert_called_once_with()
    assert "FAILED:" in caplog.text
    assert "SKIPPED:" in caplog.text


@pytest.mark.parametrize("has_history", [True, False])
def test_empty_daily_response_reuses_history_or_fails(steps, monkeypatch, tmp_path, caplog, has_history):
    raw = tmp_path / "rates"
    raw.mkdir()
    existing = raw / "rates_2026-01-14.json"
    original = json.dumps([{"date": "2026-01-14", "base": "USD", "quote": "EUR", "rate": 0.9}])
    if has_history:
        existing.write_text(original, encoding="utf-8")
    fetch = Mock(return_value=[])
    monkeypatch.setattr(ingestion, "fetch_json", fetch)
    monkeypatch.setattr(ingestion, "exchange_rate_output_dir", raw)
    monkeypatch.setattr(build, "ingest_exchange_rate_daily", ingestion.ingest_exchange_rate_daily)
    monkeypatch.setattr(build, "transform_exchange_rates",
                        lambda: transform_exchange_rates(raw, tmp_path / "warehouse.duckdb"))
    assert build.main(["--date", "2026-01-15"]) == (0 if has_history else 1)
    fetch.assert_called_once_with(ingestion.exchange_rate_url,
                                 params={"base": "USD", "date": "2026-01-15"}, timeout=60)
    assert "existing raw data is preserved" in caplog.text
    assert "existing historical data will be reused" in caplog.text
    if has_history:
        assert existing.read_text(encoding="utf-8") == original
        assert list(raw.iterdir()) == [existing]
        steps["create_reporting_view"].assert_called_once_with()
        assert "completed with warnings" in caplog.text
    else:
        assert list(raw.iterdir()) == []
        steps["create_reporting_view"].assert_not_called()
        assert "FAILED: exchange rates transformation" in caplog.text


def test_daily_ingestion_keeps_actual_publication_date(monkeypatch, tmp_path):
    records = [{"date": "2026-01-14", "base": "USD", "quote": "EUR", "rate": 0.9}]
    monkeypatch.setattr(ingestion, "fetch_json", Mock(return_value=records))
    monkeypatch.setattr(ingestion, "exchange_rate_output_dir", tmp_path)
    for _ in range(2):
        assert ingestion.ingest_exchange_rate_daily(date(2026, 1, 15)) == 1
    assert [path.name for path in tmp_path.iterdir()] == ["rates_2026-01-14.json"]
    assert json.loads((tmp_path / "rates_2026-01-14.json").read_text()) == records


@pytest.mark.parametrize("entry", [["-m", "scripts.build_daily"], ["scripts/build_daily.py"]])
def test_execution_paths(entry):
    result = subprocess.run([sys.executable, *entry, "--date", "invalid"],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True)
    assert result.returncode == 2
    assert "YYYY-MM-DD" in result.stderr
