"""Run daily ingestion and transformations and report their overall status."""

from datetime import date, timedelta

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


def main():
    target_date = date.today() - timedelta(days=1)
    operations = [
        ("countries ingestion", ingest_countries, (), None),
        ("exchange rates ingestion", ingest_exchange_rate_daily, (target_date,), None),
        ("countries transformation", transform_countries, (), "countries ingestion"),
        ("exchange rates transformation", transform_exchange_rates, (), "exchange rates ingestion"),
    ]
    failures = []
    succeeded = set()
    skipped = []
    for name, operation, args, dependency in operations:
        # Transform a source only after its ingestion succeeds, avoiding stale input on failure.
        if dependency is not None and dependency not in succeeded:
            skipped.append(name)
            print(f"SKIPPED: {name}: {dependency} did not succeed")
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
