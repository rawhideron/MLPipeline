"""Unit tests for model training and inference."""

import pytest
from unittest.mock import patch, MagicMock


class TestModelTraining:
    """Test model training functionality."""

    @patch("transformers.AutoTokenizer.from_pretrained")
    @patch("transformers.AutoModelForSequenceClassification.from_pretrained")
    def test_trainer_initialization(self, mock_model, mock_tokenizer):
        """Test SentimentTrainer initialization."""
        mock_model.return_value = MagicMock()
        mock_tokenizer.return_value = MagicMock()

        from src.models.training import SentimentTrainer

        trainer = SentimentTrainer("configs/training_config.yaml")
        assert trainer.model_name == "distilbert-base-uncased"

    def test_config_loading(self):
        """Test configuration loading."""
        from src.utils.config import load_config

        config = load_config("configs/training_config.yaml")

        assert "model" in config
        assert "training" in config
        assert "data" in config
        assert config["model"]["name"] == "distilbert-base-uncased"
        assert config["training"]["epochs"] == 3


class TestModelEvaluation:
    """Test model evaluation functionality."""

    @patch("transformers.AutoTokenizer.from_pretrained")
    @patch("transformers.AutoModelForSequenceClassification.from_pretrained")
    def test_evaluator_initialization(self, mock_model, mock_tokenizer):
        """Test ModelEvaluator initialization."""
        mock_model.return_value = MagicMock()
        mock_tokenizer.return_value = MagicMock()

        from src.models.evaluation import ModelEvaluator

        evaluator = ModelEvaluator("/path/to/model")
        assert evaluator.model_path == "/path/to/model"


class TestInference:
    """Test inference functionality."""

    @patch("transformers.AutoTokenizer.from_pretrained")
    @patch("transformers.AutoModelForSequenceClassification.from_pretrained")
    def test_predictor_initialization(self, mock_model, mock_tokenizer):
        """Test SentimentPredictor initialization."""
        mock_model.return_value = MagicMock()
        mock_tokenizer.return_value = MagicMock()

        from src.models.inference import SentimentPredictor

        predictor = SentimentPredictor("/path/to/model")
        assert predictor.model_path == "/path/to/model"
        assert predictor.labels == {0: "negative", 1: "positive"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
