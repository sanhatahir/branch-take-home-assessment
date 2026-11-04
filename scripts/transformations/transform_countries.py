"""Normalize the country snapshot into country, currency, and bridge tables."""

import json
from pathlib import Path
import duckdb


# Find the input and warehouse relative to the repository, wherever the script runs.
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "data/raw/countries/countries_raw.json"
DEFAULT_DATABASE = ROOT / "data/warehouse/branch.duckdb"


def _optional_text(value):
    """Trim available text and represent missing or unusable descriptions as NULL."""
    return (value.strip() or None) if isinstance(value, str) else None


def transform_countries(input_path=DEFAULT_INPUT, database_path=DEFAULT_DATABASE):
    """Replace the three reference tables together, upgrading older country tables in place."""
    # Read the raw country data without changing the source file.
    with open(input_path, encoding="utf-8") as file:
        records = json.load(file)

    # The source should contain a list of country records.
    if not isinstance(records, list):
        raise ValueError("Expected a list of countries")

    # Keep one name per country code and one copy of each country-currency pair.
    countries = {}
    currencies = {}
    country_currencies = set()

    for record in records:
        # Skip records that cannot provide a country code and name.
        if not isinstance(record, dict):
            continue
        code = record.get("alpha3Code")
        name = record.get("name")
        if not isinstance(code, str) or not isinstance(name, str):
            continue
        # Remove surrounding spaces and use uppercase country codes.
        code, name = code.strip().upper(), name.strip()
        if not code or not name:
            continue

        # Preserve every supplied capital in source order if a future response contains a list.
        capital = record.get("capital")
        if isinstance(capital, list):
            capital = "; ".join(text for value in capital if (text := _optional_text(value)))
        capital = _optional_text(capital)
        population = record.get("population")
        # Reject an invalid snapshot before writing; bool, fractional, and negative values are invalid.
        if population is not None and (
            type(population) is not int or not 0 <= population <= 9223372036854775807
        ):
            raise ValueError(f"Population for {code} must be a nonnegative BIGINT integer or null")

        # If a country code appears again, its last usable attributes win.
        countries[code] = (name, capital, population)
        # Collect all listed currencies, including currencies shared by countries.
        for currency in record.get("currencies", []):
            if not isinstance(currency, dict):
                continue
            currency_code = currency.get("code")
            if isinstance(currency_code, str) and currency_code.strip():
                currency_code = currency_code.strip().upper()
                country_currencies.add((code, currency_code))
                metadata = currencies.setdefault(currency_code, {"names": set(), "symbols": set()})
                currency_name = _optional_text(currency.get("name"))
                currency_symbol = _optional_text(currency.get("symbol"))
                if currency_name is not None:
                    metadata["names"].add(currency_name)
                if currency_symbol is not None:
                    metadata["symbols"].add(currency_symbol)

    # Avoid clearing the warehouse when there are no usable country records.
    if not countries:
        raise ValueError("No valid countries found; database was not changed")

    # Create the warehouse folder if it does not exist yet.
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database_path)) as connection:
        # Update all three reference tables together so a failed load leaves old data intact.
        connection.execute("BEGIN TRANSACTION")
        try:
            # Create the schema and tables on the first run.
            connection.execute("CREATE SCHEMA IF NOT EXISTS core")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS core.countries (
                    country_code VARCHAR PRIMARY KEY,
                    country_name VARCHAR NOT NULL,
                    capital VARCHAR,
                    population BIGINT
                )
            """)
            # Upgrade existing warehouses without dropping tables, history, or reporting views.
            connection.execute("ALTER TABLE core.countries ADD COLUMN IF NOT EXISTS capital VARCHAR")
            connection.execute("ALTER TABLE core.countries ADD COLUMN IF NOT EXISTS population BIGINT")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS core.currencies (
                    currency_code VARCHAR PRIMARY KEY,
                    currency_name VARCHAR,
                    currency_symbol VARCHAR
                )
            """)
            connection.execute("""
                CREATE TABLE IF NOT EXISTS core.country_currencies (
                    country_code VARCHAR NOT NULL,
                    currency_code VARCHAR NOT NULL,
                    PRIMARY KEY (country_code, currency_code)
                )
            """)
            # Replace the previous snapshot with the country data collected above.
            connection.execute("DELETE FROM core.country_currencies")
            connection.execute("DELETE FROM core.currencies")
            connection.execute("DELETE FROM core.countries")
            connection.executemany(
                "INSERT INTO core.countries (country_code, country_name, capital, population) VALUES (?, ?, ?, ?)",
                [(code, *attributes) for code, attributes in countries.items()],
            )
            # Resolve shared metadata independently using the smallest nonempty string per field.
            if currencies:
                connection.executemany(
                    "INSERT INTO core.currencies VALUES (?, ?, ?)",
                    [(code, min(metadata["names"], default=None), min(metadata["symbols"], default=None))
                     for code, metadata in sorted(currencies.items())],
                )
            if country_currencies:
                connection.executemany(
                    "INSERT INTO core.country_currencies VALUES (?, ?)",
                    sorted(country_currencies),
                )
            # Save all three tables once all inserts have succeeded.
            connection.execute("COMMIT")
        except Exception:
            # Undo this load and pass the error back to the caller.
            connection.execute("ROLLBACK")
            raise

    print(f"Loaded {len(countries)} countries, {len(currencies)} currencies, and {len(country_currencies)} currency mappings")


if __name__ == "__main__":
    # Run the transformation with the default paths when this file is executed.
    transform_countries()
