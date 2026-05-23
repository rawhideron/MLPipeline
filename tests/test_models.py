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


class TestSentimentTrainerMethods:
    """Tests for SentimentTrainer data processing methods."""

    @patch("transformers.AutoTokenizer.from_pretrained")
    def test_load_dataset_splits_into_three_splits(self, mock_tokenizer_cls):
        from src.models.training import SentimentTrainer
        from datasets import Dataset, DatasetDict

        mock_tokenizer_cls.return_value = MagicMock()
        trainer = SentimentTrainer("configs/training_config.yaml")

        fake_ds = DatasetDict(
            {"train": Dataset.from_dict({"text": ["x"] * 20, "label": [0] * 20})}
        )

        with patch("src.models.training.load_dataset", return_value=fake_ds):
            result = trainer.load_dataset()

        assert set(result.keys()) == {"train", "validation", "test"}
        total = sum(len(result[s]) for s in ("train", "validation", "test"))
        assert total == 20

    @patch("transformers.AutoTokenizer.from_pretrained")
    def test_preprocess_function_calls_tokenizer_with_correct_args(self, mock_tokenizer_cls):
        from src.models.training import SentimentTrainer

        mock_tok = MagicMock()
        mock_tok.return_value = {"input_ids": [[1, 2]], "attention_mask": [[1, 1]]}
        mock_tokenizer_cls.return_value = mock_tok

        trainer = SentimentTrainer("configs/training_config.yaml")
        trainer.tokenizer = mock_tok

        trainer.preprocess_function({"text": ["Great movie!"]})

        mock_tok.assert_called_once()
        kwargs = mock_tok.call_args[1]
        assert kwargs["truncation"] is True
        assert kwargs["max_length"] == trainer.config["data"]["max_length"]

    @patch("transformers.AutoTokenizer.from_pretrained")
    def test_prepare_dataset_returns_tokenized_splits(self, mock_tokenizer_cls):
        from src.models.training import SentimentTrainer
        from datasets import Dataset, DatasetDict

        def fake_tokenize(texts, max_length, truncation):
            return {
                "input_ids": [[1, 2]] * len(texts),
                "attention_mask": [[1, 1]] * len(texts),
            }

        mock_tok = MagicMock(side_effect=fake_tokenize)
        mock_tokenizer_cls.return_value = mock_tok

        trainer = SentimentTrainer("configs/training_config.yaml")
        trainer.tokenizer = mock_tok

        ds = DatasetDict(
            {
                split: Dataset.from_dict({"text": ["good film"] * 5, "label": [1] * 5})
                for split in ("train", "validation", "test")
            }
        )
        train_ds, val_ds, test_ds = trainer.prepare_dataset(ds)

        assert len(train_ds) == len(val_ds) == len(test_ds) == 5
        assert "labels" in train_ds.column_names
        assert "text" not in train_ds.column_names


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
