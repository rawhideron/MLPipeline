"""Unit tests for model training and inference."""

import json
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
import torch


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

        with patch(
            "src.models.training.load_dataset", return_value=mock_ds
        ) as mock_load:
            try:
                trainer.load_dataset()
            except Exception:  # noqa: BLE001, S110 -- only the call args matter, mocks don't complete the pipeline
                pass
            # load_dataset must be called with the config value, not a hardcoded string
            mock_load.assert_called_once_with(dataset_name)
            assert mock_load.call_args[0][0] == trainer.config["data"]["dataset"]


class TestModelEvaluation:
    """Test model evaluation functionality."""

    def _make_evaluator(self):
        """ModelEvaluator with mocked model and tokenizer; logits fixed at [[0.2,0.8],[0.9,0.1]]."""
        logits = torch.tensor([[0.2, 0.8], [0.9, 0.1]])
        mock_outputs = MagicMock()
        mock_outputs.logits = logits

        mock_model = MagicMock()
        mock_model.to.return_value = mock_model
        mock_model.return_value = mock_outputs

        mock_tok_output = MagicMock()
        mock_tok_output.to.return_value = {"input_ids": torch.tensor([[1, 2], [3, 4]])}
        mock_tokenizer = MagicMock()
        mock_tokenizer.return_value = mock_tok_output

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
            from src.models.evaluation import ModelEvaluator

            evaluator = ModelEvaluator("/path/to/model")
            evaluator.device = "cpu"

        evaluator.model = mock_model
        evaluator.tokenizer = mock_tokenizer
        return evaluator

    @patch("transformers.AutoTokenizer.from_pretrained")
    @patch("transformers.AutoModelForSequenceClassification.from_pretrained")
    def test_evaluator_initialization(self, mock_model, mock_tokenizer):
        mock_model.return_value = MagicMock()
        mock_tokenizer.return_value = MagicMock()

        from src.models.evaluation import ModelEvaluator

        evaluator = ModelEvaluator("/path/to/model")
        assert evaluator.model_path == "/path/to/model"

    def test_predict_batch_returns_expected_keys_and_shapes(self):
        evaluator = self._make_evaluator()
        result = evaluator.predict_batch(["Great film!", "Terrible film."])
        assert set(result.keys()) == {"predictions", "probabilities", "logits"}
        assert result["predictions"].shape == (2,)
        assert result["probabilities"].shape == (2, 2)

    def test_predict_batch_classifies_from_logits(self):
        evaluator = self._make_evaluator()
        result = evaluator.predict_batch(["Great!", "Awful!"])
        # logits [[0.2, 0.8], [0.9, 0.1]] → argmax → [1, 0]
        np.testing.assert_array_equal(result["predictions"], [1, 0])

    def test_evaluate_returns_all_metric_keys_with_correct_accuracy(self):
        evaluator = self._make_evaluator()
        evaluator.predict_batch = MagicMock(
            return_value={
                "predictions": np.array([1, 0]),
                "probabilities": np.array([[0.2, 0.8], [0.7, 0.3]]),
                "logits": np.array([[-1.0, 1.0], [1.0, -1.0]]),
            }
        )
        fake_dataset = [{"text": ["good film", "bad film"], "label": [1, 0]}]

        metrics = evaluator.evaluate(iter(fake_dataset))

        assert set(metrics.keys()) == {
            "accuracy",
            "precision",
            "recall",
            "f1",
            "confusion_matrix",
        }
        assert metrics["accuracy"] == 1.0

    def test_save_metrics_writes_valid_json(self, tmp_path):
        evaluator = self._make_evaluator()
        metrics = {"accuracy": 0.95, "f1": 0.94}
        output_path = str(tmp_path / "metrics.json")

        evaluator.save_metrics(metrics, output_path)

        with open(output_path) as f:
            loaded = json.load(f)
        assert loaded == metrics


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


class TestSentimentTrainerMethods:
    """Tests for SentimentTrainer data processing methods."""

    @patch("transformers.AutoTokenizer.from_pretrained")
    def test_load_dataset_splits_into_three_splits(self, mock_tokenizer_cls):
        from datasets import Dataset, DatasetDict

        from src.models.training import SentimentTrainer

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
    def test_preprocess_function_calls_tokenizer_with_correct_args(
        self, mock_tokenizer_cls
    ):
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
        from datasets import Dataset, DatasetDict

        from src.models.training import SentimentTrainer

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

    @patch("transformers.AutoTokenizer.from_pretrained")
    def test_train_orchestrates_components_and_returns_result(self, mock_tokenizer_cls):
        from datasets import Dataset, DatasetDict

        from src.models.training import SentimentTrainer

        mock_tokenizer_cls.return_value = MagicMock()
        trainer = SentimentTrainer("configs/training_config.yaml")

        fake_split = Dataset.from_dict(
            {
                "input_ids": [[1, 2]] * 4,
                "attention_mask": [[1, 1]] * 4,
                "labels": [1] * 4,
            }
        )
        trainer.load_dataset = MagicMock(
            return_value=DatasetDict(
                {"train": fake_split, "validation": fake_split, "test": fake_split}
            )
        )
        trainer.prepare_dataset = MagicMock(
            return_value=(fake_split, fake_split, fake_split)
        )

        mock_train_result = MagicMock()
        mock_train_result.training_loss = 0.42

        mock_hf_trainer = MagicMock()
        mock_hf_trainer.train.return_value = mock_train_result
        mock_hf_trainer.evaluate.return_value = {"eval_accuracy": 0.9, "eval_loss": 0.3}

        mock_mlflow = MagicMock()
        mock_run = MagicMock()
        mock_run.info.run_id = "abc123"
        mock_mlflow.start_run.return_value.__enter__.return_value = mock_run

        with (
            patch(
                "src.models.training.AutoModelForSequenceClassification.from_pretrained"
            ),
            patch("src.models.training.TrainingArguments"),
            patch("src.models.training.DataCollatorWithPadding"),
            patch(
                "src.models.training.Trainer", return_value=mock_hf_trainer
            ) as mock_trainer_cls,
            patch("src.models.training.mlflow", mock_mlflow),
            patch("pathlib.Path.mkdir"),
        ):
            result = trainer.train()

        assert result == {"train_loss": 0.42, "status": "completed"}
        mock_hf_trainer.train.assert_called_once()

        # Extract and verify the compute_metrics closure passed to Trainer
        compute_metrics = mock_trainer_cls.call_args[1]["compute_metrics"]
        logits = np.array([[0.1, 0.9], [0.8, 0.2]])
        labels = np.array([1, 0])
        assert compute_metrics((logits, labels)) == {"accuracy": 1.0}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
