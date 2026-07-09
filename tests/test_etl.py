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
