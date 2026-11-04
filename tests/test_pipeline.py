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
    records = [
        {"alpha3Code": " btn ", "name": "Bhutan", "capital": [" Thimphu ", "Second capital"],
         "population": 123, "currencies": [
            {"code": "BTN", "name": "Ngultrum"},
            {"code": " inr ", "name": "Z rupee", "symbol": "₹"}, {"code": "INR"},
        ]},
        {"alpha3Code": "IND", "name": "India", "capital": " New Delhi ", "population": 0,
         "currencies": [{"code": "INR", "name": " Indian rupee ", "symbol": " Rs "}]},
        {"alpha3Code": "NUL", "name": "Optional fields absent", "currencies": [{"code": "XTS"}]},
    ]
    source.write_text(json.dumps(records), encoding="utf-8")
    database = tmp_path / "warehouse.duckdb"
    transform_countries(source, database)
    # Reordering shared metadata must not change its resolution or create duplicates.
    source.write_text(json.dumps(list(reversed(records))), encoding="utf-8")
    transform_countries(source, database)
    with duckdb.connect(str(database)) as connection:
        assert connection.execute("SELECT * FROM core.countries ORDER BY country_code").fetchall() == [
            ("BTN", "Bhutan", "Thimphu; Second capital", 123),
            ("IND", "India", "New Delhi", 0),
            ("NUL", "Optional fields absent", None, None),
        ]
        assert connection.execute("SELECT * FROM core.currencies ORDER BY currency_code").fetchall() == [
            ("BTN", "Ngultrum", None), ("INR", "Indian rupee", "Rs"), ("XTS", None, None),
        ]
        assert connection.execute("""
            SELECT country_code, currency_code FROM core.country_currencies ORDER BY 1, 2
        """).fetchall() == [("BTN", "BTN"), ("BTN", "INR"), ("IND", "INR"), ("NUL", "XTS")]
        assert connection.execute("""
            SELECT count(*) FROM (
                SELECT country_code, currency_code FROM core.country_currencies
                GROUP BY ALL HAVING count(*) > 1
            )
        """).fetchone()[0] == 0


def test_legacy_country_schema_upgrade_preserves_history_and_reporting(tmp_path):
    database = tmp_path / "legacy.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE SCHEMA core")
        connection.execute("CREATE TABLE core.countries (country_code VARCHAR PRIMARY KEY, country_name VARCHAR NOT NULL)")
        connection.execute("""CREATE TABLE core.country_currencies (
            country_code VARCHAR, currency_code VARCHAR, PRIMARY KEY (country_code, currency_code)
        )""")
        connection.execute("INSERT INTO core.countries VALUES ('PER', 'Peru'), ('AUS', 'Australia')")
        connection.execute("INSERT INTO core.country_currencies VALUES ('PER', 'PEN'), ('AUS', 'AUD')")
    raw = tmp_path / "rates"
    raw.mkdir()
    (raw / "rates_2026-01-02.json").write_text(json.dumps([
        {"date": "2026-01-02", "base": "USD", "quote": "PEN", "rate": 3.5},
        {"date": "2026-01-02", "base": "USD", "quote": "AUD", "rate": 1.4},
    ]), encoding="utf-8")
    transform_exchange_rates(raw, database)
    with duckdb.connect(str(database)) as connection:
        connection.execute(REPORTING_SQL.read_text(encoding="utf-8"))
        history = connection.execute("SELECT * FROM core.exchange_rates ORDER BY quote_currency").fetchall()
    source = tmp_path / "countries.json"
    source.write_text(json.dumps([
        {"alpha3Code": "PER", "name": "Peru", "capital": "Lima", "population": 100,
         "currencies": [{"code": "PEN", "name": "Peruvian sol", "symbol": "S/."}]},
        {"alpha3Code": "AUS", "name": "Australia", "currencies": [{"code": "AUD"}]},
    ]), encoding="utf-8")
    transform_countries(source, database)
    transform_countries(source, database)
    with duckdb.connect(str(database)) as connection:
        assert connection.execute("SELECT * FROM core.exchange_rates ORDER BY quote_currency").fetchall() == history
        assert connection.execute("SELECT capital, population FROM core.countries WHERE country_code='PER'").fetchone() == ("Lima", 100)
        assert connection.execute("""
            SELECT exchange_rate FROM mart.country_exchange_rates
            WHERE source_country_code='PER' AND destination_country_code='AUS'
              AND source_currency='PEN' AND destination_currency='AUD'
        """).fetchone()[0] == pytest.approx(0.4)


@pytest.mark.parametrize("population", [-1, 1.5, True, "100", 9223372036854775808])
def test_invalid_population_preserves_existing_snapshot(tmp_path, population):
    source = tmp_path / "countries.json"
    database = tmp_path / "warehouse.duckdb"
    record = {"alpha3Code": "PER", "name": "Peru", "population": 100}
    source.write_text(json.dumps([record]), encoding="utf-8")
    transform_countries(source, database)
    source.write_text(json.dumps([dict(record, population=population)]), encoding="utf-8")
    with pytest.raises(ValueError, match="nonnegative BIGINT integer"):
        transform_countries(source, database)
    with duckdb.connect(str(database)) as connection:
        assert connection.execute("SELECT population FROM core.countries").fetchall() == [(100,)]


def test_currency_load_failure_rolls_back_all_reference_tables(tmp_path):
    database = tmp_path / "warehouse.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("CREATE SCHEMA core")
        connection.execute("""CREATE TABLE core.currencies (
            currency_code VARCHAR PRIMARY KEY,
            currency_name VARCHAR CHECK (currency_name <> 'Rejected'), currency_symbol VARCHAR
        )""")
    source = tmp_path / "countries.json"
    record = {"alpha3Code": "PER", "name": "Peru", "capital": "Lima", "population": 100,
              "currencies": [{"code": "PEN", "name": "Sol", "symbol": "S/."}]}
    source.write_text(json.dumps([record]), encoding="utf-8")
    transform_countries(source, database)
    with duckdb.connect(str(database)) as connection:
        before = {table: connection.execute(f"SELECT * FROM core.{table}").fetchall()
                  for table in ["countries", "currencies", "country_currencies"]}
    changed = dict(record, name="Changed", population=200,
                   currencies=[{"code": "PEN", "name": "Rejected"}])
    source.write_text(json.dumps([changed]), encoding="utf-8")
    with pytest.raises(duckdb.ConstraintException):
        transform_countries(source, database)
    with duckdb.connect(str(database)) as connection:
        for table, expected in before.items():
            assert connection.execute(f"SELECT * FROM core.{table}").fetchall() == expected
