"""Run independent daily ingestion operations and report their overall status."""

from datetime import date, timedelta

if __package__:
    from .ingestion.ingress_countries import ingest_countries
    from .ingestion.ingress_exchange_rates import ingest_exchange_rate_daily
else:
    from ingestion.ingress_countries import ingest_countries
    from ingestion.ingress_exchange_rates import ingest_exchange_rate_daily


def main():
    target_date = date.today() - timedelta(days=1)
    operations = [
        ("countries", ingest_countries, ()),
        ("exchange rates", ingest_exchange_rate_daily, (target_date,)),
    ]
    failures = []
    for name, operation, args in operations:
        try:
            operation(*args)
        except Exception as exc:
            failures.append(name)
            print(f"FAILED: {name}: {exc}")
        else:
            print(f"SUCCEEDED: {name}")

    if failures:
        status = "FAILED" if len(failures) == len(operations) else "PARTIAL FAILURE"
        print(f"{status}: {len(failures)} of {len(operations)} ingestion operations failed")
        return 1
    print("Daily ingestion succeeded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
