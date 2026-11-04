"""Normalize the country snapshot into two DuckDB tables."""

import json
from pathlib import Path
import duckdb


# Find the input and warehouse relative to the repository, wherever the script runs.
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INPUT = ROOT / "data/raw/countries/countries_raw.json"
DEFAULT_DATABASE = ROOT / "data/warehouse/branch.duckdb"


def transform_countries(input_path=DEFAULT_INPUT, database_path=DEFAULT_DATABASE):
    """Read the country snapshot and replace the warehouse's countries and currency mappings."""
    # Read the raw country data without changing the source file.
    with open(input_path, encoding="utf-8") as file:
        records = json.load(file)

    # The source should contain a list of country records.
    if not isinstance(records, list):
        raise ValueError("Expected a list of countries")

    # Keep one name per country code and one copy of each country-currency pair.
    countries = {}
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

        # If a country code appears again, its last valid name wins.
        countries[code] = name
        # Collect all listed currencies, including currencies shared by countries.
        for currency in record.get("currencies", []):
            if not isinstance(currency, dict):
                continue
            currency_code = currency.get("code")
            if isinstance(currency_code, str) and currency_code.strip():
                country_currencies.add((code, currency_code.strip().upper()))

    # Avoid clearing the warehouse when there are no usable country records.
    if not countries:
        raise ValueError("No valid countries found; database was not changed")

    # Create the warehouse folder if it does not exist yet.
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(database_path)) as connection:
        # Update both tables together so a failed load leaves the old data intact.
        connection.execute("BEGIN TRANSACTION")
        try:
            # Create the schema and tables on the first run.
            connection.execute("CREATE SCHEMA IF NOT EXISTS core")
            connection.execute("""
                CREATE TABLE IF NOT EXISTS core.countries (
                    country_code VARCHAR PRIMARY KEY,
                    country_name VARCHAR NOT NULL
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
            connection.execute("DELETE FROM core.countries")
            connection.executemany(
                "INSERT INTO core.countries VALUES (?, ?)", list(countries.items())
            )
            if country_currencies:
                connection.executemany(
                    "INSERT INTO core.country_currencies VALUES (?, ?)",
                    sorted(country_currencies),
                )
            # Save both tables once all inserts have succeeded.
            connection.execute("COMMIT")
        except Exception:
            # Undo this load and pass the error back to the caller.
            connection.execute("ROLLBACK")
            raise

    print(f"Loaded {len(countries)} countries and {len(country_currencies)} currency mappings")


if __name__ == "__main__":
    # Run the transformation with the default paths when this file is executed.
    transform_countries()
