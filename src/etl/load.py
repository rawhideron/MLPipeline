"""Load tidy GDP data into Postgres."""

import os
import sys

import pandas as pd
import psycopg2

from src.utils.config import load_config

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS {table} (
    period TEXT NOT NULL,
    series_code TEXT NOT NULL,
    series_name TEXT,
    table_name TEXT,
    value NUMERIC,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (period, series_code)
);
"""

UPSERT_SQL = """
INSERT INTO {table} (period, series_code, series_name, table_name, value)
VALUES (%s, %s, %s, %s, %s)
ON CONFLICT (period, series_code) DO UPDATE SET
    series_name = EXCLUDED.series_name,
    table_name = EXCLUDED.table_name,
    value = EXCLUDED.value,
    loaded_at = now();
"""


def get_connection():
    return psycopg2.connect(
        host=os.environ["POSTGRES_HOST"],
        port=os.environ.get("POSTGRES_PORT", "5432"),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        dbname=os.environ["POSTGRES_DB"],
    )


def ensure_table(conn, table: str) -> None:
    with conn.cursor() as cur:
        cur.execute(CREATE_TABLE_SQL.format(table=table))
    conn.commit()


def upsert_gdp_data(conn, df: pd.DataFrame, table: str) -> None:
    with conn.cursor() as cur:
        for row in df.itertuples(index=False):
            cur.execute(
                UPSERT_SQL.format(table=table),
                (row.period, row.series_code, row.series_name, row.table_name, row.value),
            )
    conn.commit()


def main(config_path: str) -> None:
    config = load_config(config_path)
    table = config["database"]["table_name"]
    df = pd.read_csv(config["output"]["transformed_data_path"])

    conn = get_connection()
    try:
        ensure_table(conn, table)
        upsert_gdp_data(conn, df, table)
    finally:
        conn.close()
    print(f"Loaded {len(df)} rows into {table}")


if __name__ == "__main__":
    main(sys.argv[1])
