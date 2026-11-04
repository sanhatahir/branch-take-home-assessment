"""Run daily ingestion, transformations, and reporting view creation."""

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb

logger = logging.getLogger(__name__)
LOOKBACK_DAYS = 7

if __package__:
    from .ingestion.ingress_countries import ingest_countries
    from .ingestion.ingress_exchange_rates import ingest_exchange_rate_daily
    from .ingestion.ingress_exchange_rates import run_backfill as ingest_exchange_rate_window
    from .transformations.transform_countries import transform_countries
    from .transformations.transform_exchange_rates import transform_exchange_rates
else:
    from ingestion.ingress_countries import ingest_countries
    from ingestion.ingress_exchange_rates import ingest_exchange_rate_daily
    from ingestion.ingress_exchange_rates import run_backfill as ingest_exchange_rate_window
    from transformations.transform_countries import transform_countries
    from transformations.transform_exchange_rates import transform_exchange_rates


def create_reporting_view():
    """Create or update the reporting view using the project's SQL file."""
    root = Path(__file__).resolve().parents[1]
    sql = (root / "scripts/reporting/country_exchange_rates.sql").read_text(encoding="utf-8")
    with duckdb.connect(str(root / "data/warehouse/branch.duckdb")) as connection:
        connection.execute(sql)


def parse_date(value):
    """Accept only YYYY-MM-DD calendar dates no later than today."""
    try:
        target = date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Expected a calendar date in YYYY-MM-DD format") from None
    if target.isoformat() != value:
        raise argparse.ArgumentTypeError("Expected a calendar date in YYYY-MM-DD format")
    if target > date.today():
        raise argparse.ArgumentTypeError("Date must not be in the future")
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", type=parse_date, help="Refresh rates for YYYY-MM-DD instead of the seven-day window")
    args = parser.parse_args(argv)
    # Configure console logging when the pipeline runs, leaving imports free of side effects.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    end_date = date.today()
    # Refresh seven calendar dates, including today, for missed or revised publications.
    start_date = end_date - timedelta(days=LOOKBACK_DAYS - 1)
    if args.date is not None:
        rate_operation, rate_args = ingest_exchange_rate_daily, (args.date,)
        logger.info("Starting daily pipeline with exchange-rate date %s", args.date)
    else:
        rate_operation, rate_args = ingest_exchange_rate_window, (start_date, end_date)
        logger.info("Starting daily pipeline with exchange-rate window %s through %s (inclusive)",
                    start_date, end_date)
    operations = [
        ("countries ingestion", ingest_countries, (), ()),
        ("exchange rates ingestion", rate_operation, rate_args, ()),
        ("countries transformation", transform_countries, (), ("countries ingestion",)),
        ("exchange rates transformation", transform_exchange_rates, (), ("exchange rates ingestion",)),
        ("reporting view", create_reporting_view, (),
         ("countries transformation", "exchange rates transformation")),
    ]
    failures = []
    succeeded = set()
    skipped = []
    had_warnings = False
    for name, operation, args, dependencies in operations:
        # Run each step only after all its required operations have succeeded.
        missing_dependencies = [dependency for dependency in dependencies if dependency not in succeeded]
        if missing_dependencies:
            skipped.append(name)
            logger.warning("SKIPPED: %s: %s did not succeed", name, ", ".join(missing_dependencies))
            continue
        logger.info("STARTING: %s", name)
        try:
            result = operation(*args)
            if name == "exchange rates ingestion" and result == 0:
                had_warnings = True
                logger.warning(
                    "No new exchange-rate records were received; existing historical data will be reused"
                )
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
    if had_warnings:
        logger.warning("Daily pipeline completed with warnings")
    else:
        logger.info("Daily pipeline succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
