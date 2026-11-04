# Branch Data Engineering Assessment
## Author: Sanha Tahir 

Hello hello! 

Thank you for taking the time to review this repo - I hope you have even more fun looking through this than I did making it!

*Now, what are you looking at?*

The situation we're dealing with: We want to bring in country reference data and USD-based exchange rates, load it into a DuckDB warehouse and design a schema that supports queries related to countries, currencies and currency exchange rates. 

There's two parts to this repo:
- [Part 1: Data Pipeline Implementation](part1.md) — pipeline architecture, sources, modeling, verified assessment queries, execution, testing, and trade-offs.
- [Part 2: Production Design](part2.md) — porposed design for a customer-facing application.


Technologies used: Python, `requests`, DuckDB, and SQL.

## Setup and execution

*Pre-Flight Checklist: What do you need to run this?*
- Python (developed with Python 3.13) 
- Internet access -  No API credentials are required by the current scripts!

*Initial Run:*

For the very first run, run from the repository root (PowerShell):

```powershell
################ Windows ################
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt

# Initial historical backfill command (starting 2026-01-01):
python -m scripts.ingestion.ingress_exchange_rates backfill --start 2026-01-01
# Daily build command:
python -m scripts.build_daily
#####################################

################ Mac ################
# Disclaimer: These instructions are not fully tested by me
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# Initial historical backfill:
python -m scripts.ingestion.ingress_exchange_rates backfill --start 2026-01-01

# Daily build:
python -m scripts.build_daily
#####################################

```

* For daily runs, use `python -m scripts.build_daily`. It fetches countries and exchange rate data (for the latter, it also refreshes the seven calendar dates from today minus six days through today (inclusive)), loads all available raw files, and creates the reporting view.
* Directories and the warehouse are created automatically. 
* Backfill is a separate initial step; running only the daily build does not download history beyond its seven-day refresh window.

## Running tests

With the virtual environment activated, install the test dependencies and run:

```powershell
################ Windows ################
python -m pip install -r requirements-dev.txt
python -m pytest -v
```

The tests use temporary JSON files and DuckDB databases, without live API requests
or access to your warehouse. Coverage includes country/currency attributes, schema
upgrades, rates, reporting, rollback, and the existing empty-response regression.

## Repository layout

```text
README.md                           # Overview and setup
part1.md                            # Pipeline implementation and results
part2.md                            # Production design
scripts/                            # All code for this pipeline
    ingestion/                        # Source-specific ingestion and shared utilities
    transformations/                  # Country and exchange-rate normalization/validation
    reporting/country_exchange_rates.sql
    build_daily.py                    # Five-step daily pipeline orchestration
data/                              # Generated locally; .gitkeep files retain folders
  raw/countries/countries_raw.json
  raw/frankfurter/rates_YYYY-MM-DD.json
  warehouse/branch.duckdb
initial_eda.ipynb                    # Exploratory source investigations 
querying_data.ipynb                  # Warehouse queries
```

The final reporting view is `mart.country_exchange_rates`, defined in
[scripts/reporting/country_exchange_rates.sql](scripts/reporting/country_exchange_rates.sql).
It divides destination and source USD-based rates from the same publication date from the Franfurter API.
See [Part 1](part1.md#6-assessment-queries-and-verified-results) for the PEN → AUD queries and results and see querying_data.ipynb for easy format for exploring the final data!

**IMPORTANT NOTE:**
The assignment names REST Countries; this implementation uses countries.dev as a
replacement source. [Part 1](part1.md#3-data-sources-and-ingestion) documents the difference.
