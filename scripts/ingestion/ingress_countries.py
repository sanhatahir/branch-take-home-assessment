## Importing required packages
import json
import os
import tempfile
import requests
from pathlib import Path


## Setting constants: 
# path where countries data should go 
DEFAULT_OUTPUT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "countries" / "countries_raw.json"
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

    # Initiating session:
    with requests.Session() as session:
        response = session.get(
            COUNTRIES_URL,
            params={"fields": ",".join(COUNTRIES_FIELDS)},
            timeout=30,
        )
        response.raise_for_status()
        countries = response.json()

    ## Basic validation of data ingested:
    # Make sure we don't get non-lists and we don't get empty lists:
    if not isinstance(countries, list) or not countries:
        raise ValueError("Expected a non-empty list of country objects")

    # Make sure every item is a dictionary representing a dictionary:
    if not all(isinstance(country, dict) for country in countries):
        raise ValueError("Expected each country to be an object")

    return countries



def save_countries(countries, output_path=DEFAULT_OUTPUT_PATH):
    """
    Objective: 
    Save country objects as JSON

    Args:
        countries: Source country objects
        output_path defaults to repository-root/data/countries/countries_raw.json

    Returns:
        None.

    Raises:
        OSError: Directory creation, writing, or replacement failed.
        TypeError, ValueError: Objects could not be serialized as valid JSON.
    
    Note:
        The previous snapshot is preserved if writing or replacement fails.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as file:
            temporary_path = Path(file.name)
            json.dump(countries, file, indent=2, ensure_ascii=False, allow_nan=False)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main():
    countries = fetch_countries()
    save_countries(countries)
    print(f"Successfully fetched {len(countries)} countries")
    print(f"Saved to {DEFAULT_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
