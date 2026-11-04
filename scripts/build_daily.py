"""Run daily ingestion, transformations, and reporting view creation."""

from datetime import date, timedelta
from pathlib import Path

import duckdb

if __package__:
    from .ingestion.ingress_countries import ingest_countries
    from .ingestion.ingress_exchange_rates import ingest_exchange_rate_daily
    from .transformations.transform_countries import transform_countries
    from .transformations.transform_exchange_rates import transform_exchange_rates
else:
    from ingestion.ingress_countries import ingest_countries
    from ingestion.ingress_exchange_rates import ingest_exchange_rate_daily
    from transformations.transform_countries import transform_countries
    from transformations.transform_exchange_rates import transform_exchange_rates


def create_reporting_view():
    """Create or update the reporting view using the project's SQL file."""
    root = Path(__file__).resolve().parents[1]
    sql = (root / "scripts/reporting/country_exchange_rates.sql").read_text(encoding="utf-8")
    with duckdb.connect(str(root / "data/warehouse/branch.duckdb")) as connection:
        connection.execute(sql)


def main():
    target_date = date.today() - timedelta(days=1)
    operations = [
        ("countries ingestion", ingest_countries, (), ()),
        ("exchange rates ingestion", ingest_exchange_rate_daily, (target_date,), ()),
        ("countries transformation", transform_countries, (), ("countries ingestion",)),
        ("exchange rates transformation", transform_exchange_rates, (), ("exchange rates ingestion",)),
        ("reporting view", create_reporting_view, (),
         ("countries transformation", "exchange rates transformation")),
    ]
    failures = []
    succeeded = set()
    skipped = []
    for name, operation, args, dependencies in operations:
        # Run each step only after all its required operations have succeeded.
        missing_dependencies = [dependency for dependency in dependencies if dependency not in succeeded]
        if missing_dependencies:
            skipped.append(name)
            print(f"SKIPPED: {name}: {', '.join(missing_dependencies)} did not succeed")
            continue
        try:
            operation(*args)
        except Exception as exc:
            failures.append(name)
            print(f"FAILED: {name}: {exc}")
        else:
            succeeded.add(name)
            print(f"SUCCEEDED: {name}")

    if failures:
        status = "FAILED" if not succeeded else "PARTIAL FAILURE"
        print(f"{status}: {len(failures)} failed, {len(skipped)} skipped out of {len(operations)} operations")
        return 1
    print("Daily pipeline succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
