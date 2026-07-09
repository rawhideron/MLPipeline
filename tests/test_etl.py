"""Unit tests for the GDP ETL pipeline (extract, transform, load)."""

import json
from unittest.mock import MagicMock, patch

import pandas as pd


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
