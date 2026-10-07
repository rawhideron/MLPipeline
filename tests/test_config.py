"""Unit tests for configuration utilities."""

from pathlib import Path

import pytest

from src.utils.config import get_data_path, get_model_path, load_config


class TestLoadConfig:
    def test_loads_yaml(self, tmp_path):
        config_path = tmp_path / "config.yaml"
        config_path.write_text("output:\n  model_path: /models/trained_model\n")

        assert load_config(str(config_path)) == {
            "output": {"model_path": "/models/trained_model"}
        }

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Configuration file not found"):
            load_config(str(tmp_path / "missing.yaml"))


class TestPathHelpers:
    def test_get_model_path(self):
        config = {"output": {"model_path": "/models/trained_model"}}
        assert get_model_path(config) == "/models/trained_model"

    def test_get_data_path_defaults_to_raw(self):
        path = Path(get_data_path())
        assert path.name == "raw"
        assert path.parent.name == "data"

    def test_get_data_path_custom_type(self):
        assert Path(get_data_path("processed")).name == "processed"
