## Importing required packages
from pathlib import Path

if __package__:
    from .utils import fetch_json, save_json_atomic
else:
    from utils import fetch_json, save_json_atomic


## Setting constants:
# path where countries data should go
DEFAULT_OUTPUT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "raw" / "countries" / "countries_raw.json"
)
# base URL
COUNTRIES_URL = "https://countries.dev/countries"
# additional propoerties we need
COUNTRIES_FIELDS = ["name", "alpha2Code", "alpha3Code", "currencies"]


## Defining ingestion functions:
def fetch_countries():
    """
    Objective:
    Fetch country objects

    Inputs:
    None

    Outputs:
    Non-empty list of source dictionaries
    """

    countries = fetch_json(
        COUNTRIES_URL,
        params={"fields": ",".join(COUNTRIES_FIELDS)},
        timeout=30,
    )

    ## Basic validation of data ingested:
    # Make sure we don't get non-lists and we don't get empty lists:
    if not isinstance(countries, list) or not countries:
        raise ValueError("Expected a non-empty list of country objects")

    # Make sure every item is a dictionary representing a dictionary:
    if not all(isinstance(country, dict) for country in countries):
        raise ValueError("Expected each country to be an object")

    return countries



def ingest_countries():
    countries = fetch_countries()
    save_json_atomic(countries, DEFAULT_OUTPUT_PATH)
    print(f"Successfully fetched {len(countries)} countries")
    print(f"Saved to {DEFAULT_OUTPUT_PATH}")


if __name__ == "__main__":
    ingest_countries()
