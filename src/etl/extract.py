"""Extract GDP (NIPA) data from the BEA (Bureau of Economic Analysis) API."""

import json
import os
import sys

import requests

from src.utils.config import load_config

BEA_API_URL = "https://apps.bea.gov/api/data/"


def fetch_nipa_data(user_id: str, table_name: str, frequency: str, year: str) -> dict:
    """Fetch NIPA data from the BEA API and return the parsed JSON response."""
    params = {
        "UserID": user_id,
        "method": "GetData",
        "DataSetName": "NIPA",
        "TableName": table_name,
        "Frequency": frequency,
        "Year": year,
        "ResultFormat": "JSON",
    }
    response = requests.get(BEA_API_URL, params=params, timeout=30)
    response.raise_for_status()
    return response.json()


def save_raw_data(data: dict, output_path: str) -> None:
    """Write the raw BEA API response to disk as JSON."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(data, f)


def main(config_path: str) -> None:
    config = load_config(config_path)
    user_id = os.environ["BEA_API_KEY"]
    bea_config = config["bea"]

    data = fetch_nipa_data(
        user_id=user_id,
        table_name=bea_config["table_name"],
        frequency=bea_config["frequency"],
        year=bea_config["year"],
    )
    output_path = config["output"]["raw_data_path"]
    save_raw_data(data, output_path)
    print(f"Saved raw GDP data to {output_path}")


if __name__ == "__main__":
    main(sys.argv[1])
