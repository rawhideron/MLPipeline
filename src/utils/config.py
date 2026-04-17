"""Configuration management utilities."""

import os
from pathlib import Path
from typing import Dict, Any

import yaml


def load_config(config_path: str) -> Dict[str, Any]:
    """
    Load YAML configuration file.

    Args:
        config_path: Path to YAML configuration file

    Returns:
        Configuration dictionary
    """
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    return config


def get_model_path(config: Dict) -> str:
    """Get model path from configuration."""
    return config["output"]["model_path"]


def get_data_path(data_type: str = "raw") -> str:
    """Get data directory path."""
    base_path = Path(__file__).parent.parent.parent / "data"
    return str(base_path / data_type)


if __name__ == "__main__":
    config = load_config("configs/training_config.yaml")
    print(f"Loaded config: {config}")
