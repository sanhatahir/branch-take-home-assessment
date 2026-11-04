"""Run daily ingestion, transformations, and reporting view creation."""

import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)

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
    # Configure console logging when the pipeline runs, leaving imports free of side effects.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    target_date = date.today() - timedelta(days=1)
    logger.info("Starting daily pipeline with exchange-rate target date %s", target_date)
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
            logger.warning("SKIPPED: %s: %s did not succeed", name, ", ".join(missing_dependencies))
            continue
        logger.info("STARTING: %s", name)
        try:
            operation(*args)
        except Exception:
            failures.append(name)
            logger.exception("FAILED: %s", name)
        else:
            succeeded.add(name)
            logger.info("SUCCEEDED: %s", name)

    if failures:
        status = "FAILED" if not succeeded else "PARTIAL FAILURE"
        logger.error("%s: %s failed, %s skipped out of %s operations",
                     status, len(failures), len(skipped), len(operations))
        return 1
    logger.info("Daily pipeline succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
