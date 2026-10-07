"""Unit tests for the GDP ETL pipeline (extract, transform, load)."""

import json
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest


class TestExtract:
    @patch("requests.get")
    def test_fetch_nipa_data_builds_correct_request(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"BEAAPI": {"Results": {"Data": []}}}
        mock_get.return_value = mock_response

        from src.etl.extract import fetch_nipa_data

        result = fetch_nipa_data(
            user_id="test-key", table_name="T10101", frequency="Q", year="X"
        )

        mock_get.assert_called_once()
        _, kwargs = mock_get.call_args
        assert kwargs["params"]["UserID"] == "test-key"
        assert kwargs["params"]["TableName"] == "T10101"
        assert kwargs["params"]["DataSetName"] == "NIPA"
        assert kwargs["params"]["Frequency"] == "Q"
        assert kwargs["params"]["Year"] == "X"
        assert result == {"BEAAPI": {"Results": {"Data": []}}}

    @patch("requests.get")
    def test_fetch_nipa_data_raises_on_bea_error_envelope(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "BEAAPI": {
                "Results": {"Error": {"APIErrorDescription": "Invalid API UserID"}}
            }
        }
        mock_get.return_value = mock_response

        from src.etl.extract import fetch_nipa_data

        with pytest.raises(RuntimeError, match="Invalid API UserID"):
            fetch_nipa_data(
                user_id="bad-key", table_name="T10101", frequency="Q", year="X"
            )

    def test_save_raw_data_writes_json(self, tmp_path):
        from src.etl.extract import save_raw_data

        output_path = tmp_path / "nested" / "raw.json"
        save_raw_data({"a": 1}, str(output_path))

        assert json.loads(output_path.read_text()) == {"a": 1}


class TestTransform:
    def test_parse_nipa_response_produces_tidy_dataframe(self):
        from src.etl.transform import parse_nipa_response

        raw = {
            "BEAAPI": {
                "Results": {
                    "Data": [
                        {
                            "TableName": "T10101",
                            "SeriesCode": "A191RL",
                            "LineDescription": "Gross domestic product",
                            "TimePeriod": "2023Q1",
                            "DataValue": "3.2",
                        },
                        {
                            "TableName": "T10101",
                            "SeriesCode": "A191RL",
                            "LineDescription": "Gross domestic product",
                            "TimePeriod": "2023Q2",
                            "DataValue": "1,234.5",
                        },
                    ]
                }
            }
        }

        df = parse_nipa_response(raw)

        assert list(df.columns) == [
            "period",
            "series_code",
            "series_name",
            "table_name",
            "value",
        ]
        assert len(df) == 2
        assert df.iloc[0]["period"] == "2023Q1"
        assert df.iloc[0]["value"] == 3.2
        assert df.iloc[1]["value"] == 1234.5  # comma thousands separator stripped


class TestLoad:
    def test_ensure_table_executes_create_table(self):
        from src.etl.load import ensure_table

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor

        ensure_table(conn, "gdp")

        cursor.execute.assert_called_once()
        assert "CREATE TABLE IF NOT EXISTS gdp" in cursor.execute.call_args[0][0]
        conn.commit.assert_called_once()

    def test_upsert_gdp_data_executes_one_upsert_per_row(self):
        from src.etl.load import upsert_gdp_data

        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor

        df = pd.DataFrame(
            [
                {
                    "period": "2023Q1",
                    "series_code": "A191RL",
                    "series_name": "Gross domestic product",
                    "table_name": "T10101",
                    "value": 3.2,
                }
            ]
        )

        upsert_gdp_data(conn, df, "gdp")

        assert cursor.execute.call_count == 1
        sql, params = cursor.execute.call_args[0]
        assert "ON CONFLICT (period, series_code)" in sql
        assert params == ("2023Q1", "A191RL", "Gross domestic product", "T10101", 3.2)
        conn.commit.assert_called_once()


class TestExtractErrorsAndMain:
    @patch("requests.get")
    def test_fetch_nipa_data_raises_when_data_missing(self, mock_get):
        mock_response = MagicMock()
        mock_response.json.return_value = {"BEAAPI": {"Results": {}}}
        mock_get.return_value = mock_response

        from src.etl.extract import fetch_nipa_data

        with pytest.raises(RuntimeError, match="missing expected 'Data'"):
            fetch_nipa_data(
                user_id="test-key", table_name="T10101", frequency="Q", year="X"
            )

    @patch("src.etl.extract.fetch_nipa_data")
    @patch("src.etl.extract.load_config")
    def test_main_fetches_and_saves(
        self, mock_load_config, mock_fetch, tmp_path, monkeypatch
    ):
        from src.etl.extract import main

        output_path = tmp_path / "raw" / "gdp.json"
        mock_load_config.return_value = {
            "bea": {"table_name": "T10101", "frequency": "Q", "year": "X"},
            "output": {"raw_data_path": str(output_path)},
        }
        mock_fetch.return_value = {"BEAAPI": {"Results": {"Data": []}}}
        monkeypatch.setenv("BEA_API_KEY", "test-key")

        main("config.yaml")

        mock_fetch.assert_called_once_with(
            user_id="test-key", table_name="T10101", frequency="Q", year="X"
        )
        assert json.loads(output_path.read_text()) == mock_fetch.return_value


class TestTransformMain:
    @patch("src.etl.transform.load_config")
    def test_main_writes_tidy_csv(self, mock_load_config, tmp_path):
        from src.etl.transform import main

        raw_path = tmp_path / "raw.json"
        csv_path = tmp_path / "tidy.csv"
        raw_path.write_text(
            json.dumps(
                {
                    "BEAAPI": {
                        "Results": {
                            "Data": [
                                {
                                    "TableName": "T10101",
                                    "SeriesCode": "A191RL",
                                    "LineDescription": "Gross domestic product",
                                    "TimePeriod": "2023Q1",
                                    "DataValue": "3.2",
                                }
                            ]
                        }
                    }
                }
            )
        )
        mock_load_config.return_value = {
            "output": {
                "raw_data_path": str(raw_path),
                "transformed_data_path": str(csv_path),
            }
        }

        main("config.yaml")

        df = pd.read_csv(csv_path)
        assert len(df) == 1
        assert df.iloc[0]["series_code"] == "A191RL"


class TestLoadConnectionAndMain:
    @patch("src.etl.load.psycopg2.connect")
    def test_get_connection_uses_env_vars(self, mock_connect, monkeypatch):
        from src.etl.load import get_connection

        monkeypatch.setenv("POSTGRES_HOST", "db")
        monkeypatch.delenv("POSTGRES_PORT", raising=False)
        monkeypatch.setenv("POSTGRES_USER", "user")
        monkeypatch.setenv("POSTGRES_PASSWORD", "pw")
        monkeypatch.setenv("POSTGRES_DB", "gdp")

        get_connection()

        mock_connect.assert_called_once_with(
            host="db", port="5432", user="user", password="pw", dbname="gdp"
        )

    @patch("src.etl.load.get_connection")
    @patch("src.etl.load.load_config")
    def test_main_loads_rows_and_closes_connection(
        self, mock_load_config, mock_get_connection, tmp_path
    ):
        from src.etl.load import main

        csv_path = tmp_path / "tidy.csv"
        pd.DataFrame(
            [
                {
                    "period": "2023Q1",
                    "series_code": "A191RL",
                    "series_name": "Gross domestic product",
                    "table_name": "T10101",
                    "value": 3.2,
                }
            ]
        ).to_csv(csv_path, index=False)
        mock_load_config.return_value = {
            "database": {"table_name": "gdp"},
            "output": {"transformed_data_path": str(csv_path)},
        }
        conn = MagicMock()
        cursor = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        mock_get_connection.return_value = conn

        main("config.yaml")

        # One CREATE TABLE plus one upsert for the single row
        assert cursor.execute.call_count == 2
        conn.close.assert_called_once()

    @patch("src.etl.load.ensure_table", side_effect=RuntimeError("boom"))
    @patch("src.etl.load.get_connection")
    @patch("src.etl.load.load_config")
    def test_main_closes_connection_on_failure(
        self, mock_load_config, mock_get_connection, _mock_ensure, tmp_path
    ):
        from src.etl.load import main

        csv_path = tmp_path / "tidy.csv"
        csv_path.write_text("period,series_code,series_name,table_name,value\n")
        mock_load_config.return_value = {
            "database": {"table_name": "gdp"},
            "output": {"transformed_data_path": str(csv_path)},
        }
        conn = MagicMock()
        mock_get_connection.return_value = conn

        with pytest.raises(RuntimeError, match="boom"):
            main("config.yaml")

        conn.close.assert_called_once()
