## Initial ideas:

Folder structure:

- Scripts:
    - Ingestion:
        1. countries ingestion scripts
        2. exchange rate ingestion scripts
        3. Shared utils?

Separate out concerns:
1. Transport: Shared vocab with HTTP requests, error handling, JSON parsing
2. Source-specific behaviour: API pars, backfills, response structure and organization
3. Orchestration:: Execution order, dependency and failure mgmt/failure isolation?

    - Transformation:
        1. 2x transformation script for each?
    - daily build.py: Brings it all together

* what else to keep in mind?

## Running ingestion

1. From the repository root, install dependencies with `python -m pip install -r requirements.txt`.
2. For historical backfill for exchange rates, use command: `python scripts/ingestion/ingress_exchange_rates.py backfill --start 2026-01-01`
3. daily_build.py runs daily batch pipeline 

