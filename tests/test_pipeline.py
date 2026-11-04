"""Exercise transformations and the real reporting SQL using isolated local data."""

import json
from datetime import date
from pathlib import Path

import duckdb
import pytest

from scripts.transformations.transform_countries import transform_countries
from scripts.transformations.transform_exchange_rates import transform_exchange_rates

REPORTING_SQL = Path(__file__).resolve().parents[1] / "scripts/reporting/country_exchange_rates.sql"


def prepare_reporting_database(tmp_path, days):
    countries = tmp_path / "countries.json"
    countries.write_text(json.dumps([
        {"alpha3Code": "PER", "name": "Peru", "currencies": [{"code": "PEN"}]},
        {"alpha3Code": "AUS", "name": "Australia", "currencies": [{"code": "AUD"}]},
    ]), encoding="utf-8")
    database = tmp_path / "warehouse.duckdb"
    transform_countries(countries, database)
    raw = tmp_path / "rates"
    raw.mkdir()
    for day in days:
        (raw / f"rates_{day}.json").write_text(json.dumps([
            {"date": day, "base": "USD", "quote": "PEN", "rate": 3.5},
            {"date": day, "base": "USD", "quote": "AUD", "rate": 1.4},
        ]), encoding="utf-8")
    transform_exchange_rates(raw, database)
    with duckdb.connect(str(database)) as connection:
        connection.execute(REPORTING_SQL.read_text(encoding="utf-8"))
    return database


def test_exchange_rate_idempotency_and_correction(tmp_path):
    raw = tmp_path / "rates"
    raw.mkdir()
    records = [
        {"date": "2026-01-02", "base": "USD", "quote": "PEN", "rate": 3.5},
        {"date": "2026-01-02", "base": "USD", "quote": "AUD", "rate": 1.4},
    ]
    source = raw / "rates_2026-01-02.json"
    source.write_text(json.dumps(records), encoding="utf-8")
    database = tmp_path / "warehouse.duckdb"
    transform_exchange_rates(raw, database)
    with duckdb.connect(str(database)) as connection:
        first_count = connection.execute("SELECT count(*) FROM core.exchange_rates").fetchone()[0]
    assert first_count == 2
    transform_exchange_rates(raw, database)
    with duckdb.connect(str(database)) as connection:
        assert connection.execute("SELECT count(*) FROM core.exchange_rates").fetchone()[0] == first_count
        assert connection.execute("""
            SELECT count(*) FROM (
                SELECT rate_date, base_currency, quote_currency
                FROM core.exchange_rates GROUP BY ALL HAVING count(*) > 1
            )
        """).fetchone()[0] == 0
    records[0]["rate"] = 3.6
    source.write_text(json.dumps(records), encoding="utf-8")
    transform_exchange_rates(raw, database)
    with duckdb.connect(str(database)) as connection:
        assert connection.execute("SELECT count(*) FROM core.exchange_rates").fetchone()[0] == first_count
        assert connection.execute("""
            SELECT rate FROM core.exchange_rates
            WHERE rate_date = DATE '2026-01-02' AND base_currency = 'USD' AND quote_currency = 'PEN'
        """).fetchone()[0] == pytest.approx(3.6)


def test_cross_rate_calculation(tmp_path):
    database = prepare_reporting_database(tmp_path, ["2026-01-02"])
    with duckdb.connect(str(database)) as connection:
        rows = connection.execute("""
            SELECT rate_date, exchange_rate FROM mart.country_exchange_rates
            WHERE source_country_code = 'PER' AND source_currency = 'PEN'
              AND destination_country_code = 'AUS' AND destination_currency = 'AUD'
        """).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == date(2026, 1, 2)
    assert rows[0][1] == pytest.approx(0.4)


def test_missing_publication_dates_are_not_forward_filled(tmp_path):
    database = prepare_reporting_database(tmp_path, ["2026-01-02", "2026-01-05"])
    with duckdb.connect(str(database)) as connection:
        for day, expected_count in [(2, 1), (3, 0), (4, 0), (5, 1)]:
            rows = connection.execute("""
                SELECT exchange_rate FROM mart.country_exchange_rates
                WHERE rate_date = ? AND source_country_code = 'PER' AND source_currency = 'PEN'
                  AND destination_country_code = 'AUS' AND destination_currency = 'AUD'
            """, [date(2026, 1, day)]).fetchall()
            assert len(rows) == expected_count
            if rows:
                assert rows[0][0] == pytest.approx(0.4)


def test_multiple_and_shared_country_currencies(tmp_path):
    source = tmp_path / "countries.json"
    source.write_text(json.dumps([
        {"alpha3Code": "BTN", "name": "Bhutan", "currencies": [
            {"code": "BTN"}, {"code": "INR"}, {"code": "INR"},
        ]},
        {"alpha3Code": "IND", "name": "India", "currencies": [{"code": "INR"}]},
    ]), encoding="utf-8")
    database = tmp_path / "warehouse.duckdb"
    transform_countries(source, database)
    with duckdb.connect(str(database)) as connection:
        assert connection.execute("""
            SELECT country_code, currency_code FROM core.country_currencies ORDER BY 1, 2
        """).fetchall() == [("BTN", "BTN"), ("BTN", "INR"), ("IND", "INR")]
        assert connection.execute("""
            SELECT count(*) FROM (
                SELECT country_code, currency_code FROM core.country_currencies
                GROUP BY ALL HAVING count(*) > 1
            )
        """).fetchone()[0] == 0
