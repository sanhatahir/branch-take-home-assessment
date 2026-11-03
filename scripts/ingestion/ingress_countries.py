# Importing required packages:
import json
import os
from pathlib import Path
import requests
from dotenv import load_dotenv


DEFAULT_OUTPUT_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "countries" / "countries_raw.json"
)
COUNTRIES_URL = "https://api.restcountries.com/countries/v5"
COUNTRIES_FIELDS = [
    "names.common",
    "names.official",
    "codes.alpha_2",
    "codes.alpha_3",
    "currencies",
]


def fetch_countries(api_key=None):
    """Return all source country objects from the paginated v5 API.

    api_key is an optional bearer token. Otherwise, load countries_api_key
    from the environment or repository-root .env. Request, JSON, missing-key,
    and pagination errors propagate to callers. No files are written.
    """
    if api_key is None:
        load_dotenv(Path(__file__).resolve().parents[2] / ".env")
        api_key = os.environ["countries_api_key"]

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    countries = []
    offset = 0
    limit = 100

    with requests.Session() as session:
        while True:
            response = session.get(
                COUNTRIES_URL,
                headers=headers,
                params={
                    "response_fields": ",".join(COUNTRIES_FIELDS),
                    "limit": limit,
                    "offset": offset,
                },
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()["data"]
            records = data["objects"]
            meta = data["meta"]
            countries.extend(records)

            if not meta["more"]:
                break
            if not records:
                raise ValueError(
                    "API indicates more data, but returned an empty page"
                )
            offset += len(records)

    if len(countries) != meta["total"]:
        raise ValueError(
            f"Expected {meta['total']} countries, received {len(countries)}"
        )
    return countries


def save_countries(countries, output_path=DEFAULT_OUTPUT_PATH):
    """Write source country objects as JSON to the supplied destination."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(countries, file, indent=2, ensure_ascii=False)


def main():
    countries = fetch_countries()
    save_countries(countries)
    print(f"Successfully fetched {len(countries)} countries")
    print(f"Saved to {DEFAULT_OUTPUT_PATH}")


if __name__ == "__main__":
    main()
