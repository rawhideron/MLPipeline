"""Unit tests for model training and inference."""

import pytest
import torch
from unittest.mock import patch, MagicMock


class TestModelTraining:
    """Test model training functionality."""

    @patch("transformers.AutoTokenizer.from_pretrained")
    @patch("transformers.AutoModelForSequenceClassification.from_pretrained")
    def test_trainer_initialization(self, mock_model, mock_tokenizer):
        mock_model.return_value = MagicMock()
        mock_tokenizer.return_value = MagicMock()

        from src.models.training import SentimentTrainer

        trainer = SentimentTrainer("configs/training_config.yaml")
        assert trainer.model_name == "distilbert-base-uncased"

    def test_config_loading(self):
        from src.utils.config import load_config

        config = load_config("configs/training_config.yaml")

        assert "model" in config
        assert "training" in config
        assert "data" in config
        assert config["model"]["name"] == "distilbert-base-uncased"
        assert config["training"]["epochs"] == 3

    @patch("transformers.AutoTokenizer.from_pretrained")
    @patch("transformers.AutoModelForSequenceClassification.from_pretrained")
    def test_load_dataset_uses_config_name(self, mock_model, mock_tokenizer):
        """load_dataset() must pass dataset name from config, not a hardcoded string."""
        mock_model.return_value = MagicMock()
        mock_tokenizer.return_value = MagicMock()

        from src.models.training import SentimentTrainer

        trainer = SentimentTrainer("configs/training_config.yaml")
        dataset_name = trainer.config["data"]["dataset"]
        assert isinstance(dataset_name, str) and len(dataset_name) > 0

        val_test_mock = MagicMock()
        val_test_mock.train_test_split.return_value = {
            "train": MagicMock(),
            "test": MagicMock(),
        }
        train_split_mock = MagicMock()
        train_split_mock.__getitem__ = MagicMock(
            side_effect=lambda k: val_test_mock if k == "test" else MagicMock()
        )
        mock_ds = MagicMock()
        mock_ds.__getitem__ = MagicMock(return_value=MagicMock())
        mock_ds["train"].train_test_split.return_value = train_split_mock

        with patch("src.models.training.load_dataset", return_value=mock_ds) as mock_load:
            try:
                trainer.load_dataset()
            except Exception:
                pass
            # load_dataset must be called with the config value, not a hardcoded string
            mock_load.assert_called_once_with(dataset_name)
            assert mock_load.call_args[0][0] == trainer.config["data"]["dataset"]


class TestModelEvaluation:
    """Test model evaluation functionality."""

    @patch("transformers.AutoTokenizer.from_pretrained")
    @patch("transformers.AutoModelForSequenceClassification.from_pretrained")
    def test_evaluator_initialization(self, mock_model, mock_tokenizer):
        mock_model.return_value = MagicMock()
        mock_tokenizer.return_value = MagicMock()

        from src.models.evaluation import ModelEvaluator

        evaluator = ModelEvaluator("/path/to/model")
        assert evaluator.model_path == "/path/to/model"


class TestInference:
    """Test SentimentPredictor inference."""

    @patch("transformers.AutoTokenizer.from_pretrained")
    @patch("transformers.AutoModelForSequenceClassification.from_pretrained")
    def test_predictor_initialization(self, mock_model, mock_tokenizer):
        mock_model.return_value = MagicMock()
        mock_tokenizer.return_value = MagicMock()

        from src.models.inference import SentimentPredictor

        predictor = SentimentPredictor("/path/to/model")
        assert predictor.model_path == "/path/to/model"
        assert predictor.labels == {0: "negative", 1: "positive"}

    def _make_predictor_with_logits(self, logits: torch.Tensor):
        """Return a SentimentPredictor whose model produces the given logits."""
        mock_outputs = MagicMock()
        mock_outputs.logits = logits

        # model.to(device) must return the same mock so self.model is callable
        mock_model = MagicMock()
        mock_model.to.return_value = mock_model
        mock_model.return_value = mock_outputs

        mock_tokenizer = MagicMock()
        token_result = MagicMock()
        token_result.to.return_value = token_result
        mock_tokenizer.return_value = token_result

        with (
            patch(
                "transformers.AutoModelForSequenceClassification.from_pretrained",
                return_value=mock_model,
            ),
            patch(
                "transformers.AutoTokenizer.from_pretrained",
                return_value=mock_tokenizer,
            ),
        ):
            from src.models.inference import SentimentPredictor

            predictor = SentimentPredictor("/path/to/model")
            predictor.device = "cpu"

        predictor.model = mock_model
        predictor.tokenizer = mock_tokenizer
        return predictor, mock_model

    def test_predict_returns_expected_keys(self):
        logits = torch.tensor([[0.3, 2.1]])
        predictor, _ = self._make_predictor_with_logits(logits)

        result = predictor.predict("This is great!")

        assert "label" in result
        assert "confidence" in result
        assert "probabilities" in result
        assert result["label"] == "positive"
        assert 0.0 <= result["confidence"] <= 1.0

    def test_predict_batch_returns_list(self):
        logits = torch.tensor([[0.3, 2.1], [1.8, 0.2]])
        predictor, _ = self._make_predictor_with_logits(logits)

        results = predictor.predict_batch(["Great film!", "Terrible film."])

        assert len(results) == 2
        assert results[0]["label"] == "positive"
        assert results[1]["label"] == "negative"
        for r in results:
            assert "confidence" in r
            assert "probabilities" in r

    def test_predict_batch_uses_single_forward_pass(self):
        """predict_batch() must call model once, not once per text."""
        logits = torch.tensor([[0.3, 2.1], [1.8, 0.2], [0.1, 0.9]])
        predictor, mock_model = self._make_predictor_with_logits(logits)

        predictor.predict_batch(["A", "B", "C"])

        assert mock_model.call_count == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
