# Branch Data Engineering Assessment

Hello! 

Thank you for taking the time to review this repo - I hope you have even more fun looking through this than I did making it!

*Now, what are you looking at?*

A Python batch pipeline that ingests country reference data and USD-based exchange rates, normalizes them into DuckDB, and exposes country-to-country conversions through SQL.

Technologies: Python, `requests`, DuckDB, and SQL.

- [Part 1: Data Pipeline Implementation](part1.md) — pipeline architecture, sources, modeling, verified assessment queries, execution, and trade-offs.
- [Part 2: Production Design](part2.md) — placeholder; response in progress.

## Setup and execution

*Pre-Flight Checklist: What do you need to run this?*
- Python (developed with Python 3.13) 
- Internet access -  No API credentials are required by the current scripts!

*Initial Run:*
Run from the repository root (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# Initial historical backfill, followed by the complete build.
python -m scripts.ingestion.ingress_exchange_rates backfill --start 2026-01-01
python -m scripts.build_daily
```

* For subsequent daily runs, use `python -m scripts.build_daily`. It fetches countries and refreshes the seven calendar dates from today minus seven days through yesterday (inclusive), loads all available raw files, and creates the reporting view.
* Directories and the warehouse are created automatically. 
* Backfill is a separate initial step; running only the daily build does not download history beyond its seven-day refresh window.

## Running tests

With the virtual environment activated, install the test dependencies and run:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest -v
```

The four pipeline tests use temporary JSON files and DuckDB databases, without live
API requests or access to your warehouse. The existing empty-response regression
test is also included (five tests total).

## Repository layout

```text
README.md                           # Overview and setup
part1.md                            # Pipeline implementation and results
part2.md                            # Production design placeholder
scripts/
  ingestion/                        # Source-specific ingestion and shared utilities
  transformations/                  # Country and exchange-rate normalization
  reporting/country_exchange_rates.sql
  build_daily.py                    # Five-step daily pipeline
data/                              # Generated locally; .gitkeep files retain folders
  raw/countries/countries_raw.json
  raw/frankfurter/rates_YYYY-MM-DD.json
  warehouse/branch.duckdb
initial_eda.ipynb                    # Exploratory source investigations
querying_data.ipynb                  # Warehouse queries
```

The reporting view is `mart.country_exchange_rates`, defined in
[scripts/reporting/country_exchange_rates.sql](scripts/reporting/country_exchange_rates.sql).
It divides destination and source USD-based rates from the same publication date.
See [Part 1](part1.md#6-assessment-queries-and-verified-results) for the PEN → AUD queries and results.

**IMPORTANT NOTE:**
The assignment names REST Countries; this implementation uses countries.dev as a
replacement source. [Part 1](part1.md#3-data-sources-and-ingestion) documents the difference.
