"""Transform raw BEA NIPA JSON into a tidy DataFrame for loading into Postgres."""

import json
import sys

import pandas as pd

from src.utils.config import load_config

TIDY_COLUMNS = ["period", "series_code", "series_name", "table_name", "value"]


def parse_nipa_response(raw: dict) -> pd.DataFrame:
    """Reshape a raw BEA NIPA API response into a tidy DataFrame."""
    records = raw["BEAAPI"]["Results"]["Data"]
    rows = [
        {
            "period": record["TimePeriod"],
            "series_code": record["SeriesCode"],
            "series_name": record["LineDescription"],
            "table_name": record["TableName"],
            "value": float(record["DataValue"].replace(",", "")),
        }
        for record in records
    ]
    return pd.DataFrame(rows, columns=TIDY_COLUMNS)


def main(config_path: str) -> None:
    config = load_config(config_path)
    with open(config["output"]["raw_data_path"]) as f:
        raw = json.load(f)

    df = parse_nipa_response(raw)
    output_path = config["output"]["transformed_data_path"]
    df.to_csv(output_path, index=False)
    print(f"Wrote {len(df)} rows to {output_path}")


if __name__ == "__main__":
    main(sys.argv[1])
