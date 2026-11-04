# Branch Data Engineering Assessment

A local pipeline that combines country and currency data from countries.dev with
USD-based exchange rates from Frankfurter. Raw JSON is normalized into DuckDB,
then exposed through a country-to-country exchange-rate reporting view.

## First-time setup

Python and internet access are required. The project was developed with Python 3.13.
Run the following commands from the repository root. Examples use Windows PowerShell.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

The pipeline uses `requests` and `duckdb`. No API credentials or `.env` configuration
are required by the current ingestion scripts.

To populate history and build the warehouse for the first time:

```powershell
python -m scripts.ingestion.ingress_exchange_rates backfill --start 2026-01-01
python -m scripts.build_daily
```

The backfill downloads historical rates through today. The daily build fetches
countries and yesterday's rates, loads all available raw rate files, and creates
the reporting view. Output directories and the database are created automatically.
Raw data and the database are generated locally and are not included in Git.

For a smaller first run, omit the backfill and run only `python -m scripts.build_daily`.
This builds the warehouse with the rates returned for yesterday, rather than a
historical series.

## Daily execution

```powershell
python -m scripts.build_daily
```

The build runs these five steps in order:

1. Fetch the latest country snapshot.
2. Fetch USD-based rates for yesterday.
3. Replace the country and country-currency tables if country ingestion succeeded.
4. Insert or update exchange rates if exchange-rate ingestion succeeded.
5. Create or replace the reporting view if both transformations succeeded.

A failed source does not prevent the other source from running. Dependent steps
are skipped. The build logs timestamps, step starts, successes, warnings for skipped
steps, and tracebacks for failures. Individual scripts also print progress messages.
Exit status is `0` when all steps succeed and `1` on any failure.

Yesterday is based on the execution machine's local calendar date. Using the previous
day reduces the chance of requesting a day whose source publications are still in
progress; it does not guarantee every currency is available.

## Project layout

```text
scripts/
  ingestion/
    utils.py                      # Shared HTTP requests and atomic JSON writes
    ingress_countries.py          # Country snapshot ingestion
    ingress_exchange_rates.py    # Daily and historical rate ingestion
  transformations/
    transform_countries.py       # Countries and country-currency relationships
    transform_exchange_rates.py  # Bulk exchange-rate upsert
  reporting/
    country_exchange_rates.sql   # Country-to-country reporting view
  build_daily.py                 # Pipeline orchestration and status reporting

data/
  raw/
    countries/countries_raw.json
    frankfurter/rates_YYYY-MM-DD.json
  warehouse/branch.duckdb

initial_eda.ipynb                  # Source-data exploration
querying_data.ipynb                # Warehouse querying examples
```

The data directories retain `.gitkeep` placeholders; generated data, DuckDB files,
and write-ahead logs are ignored by Git.

## Running individual steps

Fetch countries, fetch a particular rate date, or backfill a bounded period:

```powershell
python -m scripts.ingestion.ingress_countries
python -m scripts.ingestion.ingress_exchange_rates daily --date 2026-01-05
python -m scripts.ingestion.ingress_exchange_rates backfill --start 2026-01-01 --end 2026-01-31
```

Without overrides, daily ingestion requests yesterday; backfill starts at
2026-01-01 and ends today. Files are named using the published dates in the response,
which can differ from the requested dates. Returned dates are not filtered to the
requested range. Empty API responses create no files.

To load existing raw files without making API requests:

```powershell
python -m scripts.transformations.transform_countries
python -m scripts.transformations.transform_exchange_rates
```

The transformation command-line entry points use the default paths shown above;
they do not accept path flags. Their Python functions accept path arguments when
called directly. Direct script execution, such as `python scripts/build_daily.py`,
is also supported.

To create or update only the reporting view after loading the core tables:

```powershell
python -c "from scripts.build_daily import create_reporting_view; create_reporting_view()"
```

## Warehouse model

All objects live in `data/warehouse/branch.duckdb`.

| Object | Columns | Grain |
| --- | --- | --- |
| `core.countries` | `country_code VARCHAR`, `country_name VARCHAR` | One row per country code |
| `core.country_currencies` | `country_code VARCHAR`, `currency_code VARCHAR` | One row per distinct country-currency pair |
| `core.exchange_rates` | `rate_date DATE`, `base_currency VARCHAR`, `quote_currency VARCHAR`, `rate DOUBLE` | One row per date, base currency, and quote currency |
| `mart.country_exchange_rates` | Date, source/destination country codes and names, source/destination currencies, exchange rate | One row per date, source country/currency, and destination country/currency |

Primary keys enforce the core table grains. Countries join to currency mappings on
`country_code`; mappings join to rates on `currency_code = quote_currency`.
These are logical relationships, without physical foreign-key constraints.
Multiple currencies per country and currencies shared across countries are preserved.

The reporting object is a SQL view, not a stored table. It joins source and
destination observations on the same published date and calculates:

```text
exchange_rate = destination_usd_rate / source_usd_rate
```

The result is destination-currency units per one source-currency unit. Only
combinations with both USD-based rates available on that date appear. Same-country
and same-currency combinations are included. Missing rates are not forward-filled,
and USD itself participates only if a USD-to-USD rate exists in the core data.
The view reflects subsequent core-table updates automatically.

## Querying the warehouse

Open `querying_data.ipynb` with the repository root as the working directory and
use a notebook kernel with the project dependencies installed. Notebook tooling is
separate from the pipeline's requirements.

For example, retrieve the latest available Peruvian sol to Australian dollar rate:

```python
import duckdb

with duckdb.connect("data/warehouse/branch.duckdb", read_only=True) as con:
    result = con.execute("""
        SELECT rate_date, source_currency, destination_currency, exchange_rate
        FROM mart.country_exchange_rates
        WHERE source_country_code = 'PER'
          AND destination_country_code = 'AUS'
          AND source_currency = 'PEN'
          AND destination_currency = 'AUD'
        ORDER BY rate_date DESC
        LIMIT 1
    """).fetchall()

print(result)
```

The rate represents AUD per 1 PEN. Here, "latest" means the most recent matching
published date stored in the warehouse, not a live trading rate. An empty result
means no matching date has both rates. Check `rate_date` for freshness.

Close notebook database connections before running a build. A connection in another
process can prevent DuckDB from opening the warehouse for writing. The `with` block
above closes its connection automatically.

## Loading behavior and current limitations

- Raw snapshots use temporary files and atomic replacement to preserve the previous
  file if a write fails. Transformations read raw files without modifying them.
- Country names are trimmed; country and currency codes are trimmed and uppercased.
  The current validation checks for nonempty strings, not three-letter ISO membership.
  Annotated source codes such as `IMP[G]`, `JEP[G]`, and `TVD[G]` remain in the mappings
  and may have no corresponding exchange rate.
- A successful country load replaces both country tables in one transaction. Missing
  country codes/names are skipped. For repeated country codes, the last usable name
  wins, while currency mappings are collected across those records. A missing currency
  field is allowed; malformed currency containers can stop the load.
- Rates require a parseable date, a USD base, a nonempty quote, and a finite positive
  numeric value after conversion. Unusable records are skipped; rejected-record counts
  and conflict reports are not currently produced. Unreadable or malformed JSON files
  stop the transformation rather than being skipped.
- Rates are deduplicated by published date, base, and quote. Files are processed in
  sorted filename order; the last usable record for a duplicate key wins. Conflicting
  duplicates are not separately flagged.
- Exchange-rate loading processes all available raw files and uses one bulk SQL upsert.
  Corrected values replace existing keys; other stored history remains. Repeated runs
  do not create duplicate keys. All-invalid or empty input fails before updating the
  database, and database errors roll back the transformation's transaction.
- Transactions apply per transformation, not across the entire pipeline. A failed
  build can leave one source refreshed and the other unchanged. An existing reporting
  view remains queryable and reflects whichever core updates committed.
- Country mappings represent the latest snapshot, not historical currency ownership.
  Rates use floating-point `DOUBLE` values; results are reference conversions and
  do not include transfer fees or transaction spreads.
