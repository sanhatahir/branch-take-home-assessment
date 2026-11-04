# Importing required packages:
import argparse
import logging
from datetime import date
from pathlib import Path

if __package__:
    from .utils import fetch_json, save_json_atomic
else:
    from utils import fetch_json, save_json_atomic


logger = logging.getLogger(__name__)

exchange_rate_url = "https://api.frankfurter.dev/v2/rates"
exchange_rate_start_date = date(2026, 1, 1)
exchange_rate_output_dir = (
    Path(__file__).resolve().parents[2] / "data" / "raw" / "frankfurter"
)


def fetch_rates(start_date, end_date=None):
    """
    Objective:
    get USD-based records for a date and/or backfill?

    start_date and optional end_date are datetime.date objects.
    """

    exchange_rate_params = {"base": "USD"}

    if end_date is None:
        exchange_rate_params["date"] = start_date.isoformat()
    else:
        exchange_rate_params["from"] = start_date.isoformat()
        exchange_rate_params["to"] = end_date.isoformat()

    records = fetch_json(
        exchange_rate_url,
        params=exchange_rate_params,
        timeout=60,
    )
    if not isinstance(records, list):
        raise ValueError("Expected a list of rate records")

    return records


def save_raw(records, filename):
    """
    Objective:
    save records to filename under the raw output directory

    """
    path = exchange_rate_output_dir / filename
    save_json_atomic(records, path)

    print(f"Saved {len(records)} records to {path}")


def _save_daily_records(records):
    """Group records by validated API dates before writing any daily files."""
    by_date = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("date"), str):
            raise ValueError("Expected a rate object with an ISO date string")
        rate_date = date.fromisoformat(record["date"]).isoformat()
        if rate_date != record["date"]:
            raise ValueError("Expected rate date in YYYY-MM-DD format")
        by_date.setdefault(rate_date, []).append(record)

    for rate_date, daily_records in sorted(by_date.items()):
        save_raw(daily_records, f"rates_{rate_date}.json")


def run_backfill(start_date, end_date):
    """
    Objective: Fetch a date range and replace one JSON file per actual API rate date.

    Inputs are datetime.date objects. Returns the saved record count; errors propagate.
    Empty responses create no files. Records are never forward-filled.
    """
    records = fetch_rates(start_date, end_date)
    if not records:
        logger.warning(
            "No exchange-rate records received from %s to %s; existing raw data is preserved",
            start_date, end_date,
        )
        return 0
    _save_daily_records(records)
    return len(records)


def ingest_exchange_rate_daily(target_date):
    """Fetch a requested datetime.date and write files grouped by API rate date.

    Returns None; fetch/write errors propagate. Actual dates may differ from
    target_date or from one another. Empty responses are reported without files.
    """
    records = fetch_rates(target_date)
    if not records:
        print(f"No rates available for {target_date}")
        return
    _save_daily_records(records)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "mode",
        choices=["backfill", "daily"],
    )

    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--start", type=date.fromisoformat)
    parser.add_argument("--end", type=date.fromisoformat)

    args = parser.parse_args()

    if args.mode == "backfill":
        start = args.start or exchange_rate_start_date
        end = args.end or date.today()

        if start > end:
            parser.error("Start date must be <= end date")

        run_backfill(start, end)

    elif args.mode == "daily":
        target = args.date or date.today()

        ingest_exchange_rate_daily(target)
