"""Load raw Frankfurter rate files into DuckDB."""

import json
from datetime import date
from pathlib import Path
import duckdb

# Locate the repository so default paths work from any working directory.
ROOT = Path(__file__).resolve().parents[2]
# Read the daily JSON files produced by both daily ingestion and historical backfills.
INPUT_DIR = ROOT / "data/raw/frankfurter"
# Store normalized rates in the same warehouse used by the country transformation.
DATABASE = ROOT / "data/warehouse/branch.duckdb"


def transform_exchange_rates(input_dir=INPUT_DIR, database_path=DATABASE):
    """Read raw rate files and insert or update their published daily rates in DuckDB."""
    # Process matching filenames in sorted order so duplicate handling is repeatable.
    files = sorted(Path(input_dir).glob("rates_*.json"))
    # Stop early if there are no source files to process.
    if not files:
        raise FileNotFoundError(f"No exchange-rate files found in {input_dir}")

    print(f"Reading exchange rates from {len(files)} files", flush=True)
    # Keep one rate per published date, base currency, and quote currency.
    rates = {}
    for path in files:
        # Read each raw file without modifying it; unreadable or malformed JSON stops the load.
        records = json.loads(path.read_text(encoding="utf-8"))
        # Each file must contain a list of individual exchange-rate records.
        if not isinstance(records, list):
            raise ValueError(f"Expected a list of rates in {path.name}")

        for record in records:
            # Skip entries that are not JSON objects.
            if not isinstance(record, dict):
                continue
            try:
                # Use the date published in the record rather than the filename.
                rate_date = date.fromisoformat(record["date"])
                # Remove surrounding spaces and standardize currency codes to uppercase.
                base = record["base"].strip().upper()
                quote = record["quote"].strip().upper()
                # Convert the source value to a number for storage and calculations.
                rate = float(record["rate"])
            except (KeyError, TypeError, ValueError, AttributeError):
                # Skip records with missing fields or values that cannot be converted.
                continue

            # Accept USD-based rates with a nonempty quote and a finite positive value.
            if base != "USD" or not quote or not (0 < rate < float("inf")):
                continue
            # The last record encountered for a matching key replaces earlier values.
            rates[(rate_date, base, quote)] = rate

    # Leave the warehouse untouched if no usable rates were found.
    if not rates:
        raise ValueError("No valid exchange rates found")

    print(f"Prepared {len(rates)} distinct exchange rates for loading", flush=True)
    # Pass one array per column so DuckDB can process the whole batch in one statement.
    rate_dates = [day for day, base, quote in rates]
    base_currencies = [base for day, base, quote in rates]
    quote_currencies = [quote for day, base, quote in rates]
    rate_values = list(rates.values())

    # Create the warehouse directory if this is the first load.
    database_path = Path(database_path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    # Open the persistent database and close the connection when this block finishes.
    with duckdb.connect(str(database_path)) as connection:
        # Save all rate changes together so a failed load cannot leave partial updates.
        connection.execute("BEGIN TRANSACTION")
        try:
            # Reuse the shared core schema without clearing its existing tables.
            connection.execute("CREATE SCHEMA IF NOT EXISTS core")
            # Create the rate table if needed; its primary key prevents duplicate daily pairs.
            connection.execute("""
                CREATE TABLE IF NOT EXISTS core.exchange_rates (
                    rate_date DATE NOT NULL,
                    base_currency VARCHAR NOT NULL,
                    quote_currency VARCHAR NOT NULL,
                    rate DOUBLE NOT NULL,
                    PRIMARY KEY (rate_date, base_currency, quote_currency)
                )
            """)
            # Insert new keys or update their rates while retaining other stored history.
            # UNNEST turns the four equally sized arrays into aligned rows for a bulk upsert.
            # On a key conflict, excluded.rate means the incoming value replaces the stored rate.
            print(f"Upserting {len(rates)} exchange rates into DuckDB", flush=True)
            connection.execute("""
                INSERT INTO core.exchange_rates
                SELECT unnest(?::DATE[]), unnest(?::VARCHAR[]),
                       unnest(?::VARCHAR[]), unnest(?::DOUBLE[])
                ON CONFLICT (rate_date, base_currency, quote_currency)
                DO UPDATE SET rate = excluded.rate
            """, [rate_dates, base_currencies, quote_currencies, rate_values])
            # Make all inserts and updates permanent after the batch succeeds.
            print("Committing exchange-rate changes", flush=True)
            connection.execute("COMMIT")
        except Exception:
            # Restore the previous database state and pass the error to the caller.
            connection.execute("ROLLBACK")
            raise

    # Report the number of distinct rate keys processed, including updates to existing rows.
    print(f"Loaded {len(rates)} exchange rates from {len(files)} files")


if __name__ == "__main__":
    # Run with the default source directory and warehouse when executed as a script.
    transform_exchange_rates()
