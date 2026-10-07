"""Unit tests for InferenceHandler."""

from unittest.mock import MagicMock, patch

import pytest


def _make_model_config(model_name="distilbert-base-uncased", num_labels=2):
    cfg = MagicMock()
    cfg.name_or_path = model_name
    cfg.num_labels = num_labels
    cfg.id2label = {0: "negative", 1: "positive"}
    return cfg


@pytest.fixture
def mock_predictor_class():
    """Patch SentimentPredictor so InferenceHandler never hits disk."""
    with patch("serving.inference_handler.SentimentPredictor") as mock_cls:
        mock_instance = MagicMock()
        mock_instance.model.config = _make_model_config()
        mock_cls.return_value = mock_instance
        yield mock_cls, mock_instance


class TestInferenceHandlerInit:
    def test_ready_when_model_loads(self, mock_predictor_class):
        from serving.inference_handler import InferenceHandler

        handler = InferenceHandler("/models/trained_model")
        assert handler.is_ready() is True

    def test_not_ready_when_model_load_fails(self):
        with patch(
            "serving.inference_handler.SentimentPredictor",
            side_effect=RuntimeError("no model"),
        ):
            from serving.inference_handler import InferenceHandler

            handler = InferenceHandler("/models/trained_model")
            assert handler.is_ready() is False

    def test_model_path_stored(self, mock_predictor_class):
        from serving.inference_handler import InferenceHandler

        handler = InferenceHandler("/custom/path")
        assert handler.model_path == "/custom/path"


class TestPredict:
    def test_predict_returns_result(self, mock_predictor_class):
        _, mock_instance = mock_predictor_class
        mock_instance.predict.return_value = {
            "text": "Great film!",
            "label": "positive",
            "confidence": 0.95,
            "probabilities": {"negative": 0.05, "positive": 0.95},
        }

        from serving.inference_handler import InferenceHandler

        handler = InferenceHandler("/models/trained_model")
        result = handler.predict("Great film!")

        assert result == mock_instance.predict.return_value
        mock_instance.predict.assert_called_once_with("Great film!")

    def test_predict_raises_when_not_ready(self):
        with patch(
            "serving.inference_handler.SentimentPredictor",
            side_effect=RuntimeError("no model"),
        ):
            from serving.inference_handler import InferenceHandler

            handler = InferenceHandler("/models/trained_model")

        with pytest.raises(RuntimeError, match="not ready"):
            handler.predict("anything")


class TestPredictBatch:
    def test_predict_batch_returns_list(self, mock_predictor_class):
        _, mock_instance = mock_predictor_class
        mock_instance.predict_batch.return_value = [
            {
                "text": "Good",
                "label": "positive",
                "confidence": 0.9,
                "probabilities": {"negative": 0.1, "positive": 0.9},
            },
            {
                "text": "Bad",
                "label": "negative",
                "confidence": 0.8,
                "probabilities": {"negative": 0.8, "positive": 0.2},
            },
        ]

        from serving.inference_handler import InferenceHandler

        handler = InferenceHandler("/models/trained_model")
        results = handler.predict_batch(["Good", "Bad"])

        assert results == mock_instance.predict_batch.return_value
        mock_instance.predict_batch.assert_called_once_with(["Good", "Bad"])

    def test_predict_batch_raises_when_not_ready(self):
        with patch(
            "serving.inference_handler.SentimentPredictor",
            side_effect=RuntimeError("no model"),
        ):
            from serving.inference_handler import InferenceHandler

            handler = InferenceHandler("/models/trained_model")

        with pytest.raises(RuntimeError, match="not ready"):
            handler.predict_batch(["anything"])


class TestGetModelInfo:
    def test_model_info_when_ready(self, mock_predictor_class):
        _, mock_instance = mock_predictor_class
        mock_instance.model.config = _make_model_config("distilbert-base-uncased", 2)

        from serving.inference_handler import InferenceHandler

        handler = InferenceHandler("/models/trained_model")
        info = handler.get_model_info()

        assert info == {
            "model_path": "/models/trained_model",
            "model_loaded": True,
            "model_name": "distilbert-base-uncased",
            "task": "sentiment-classification",
            "num_labels": 2,
            "labels": ["negative", "positive"],
        }

    def test_model_info_with_no_label_mapping(self, mock_predictor_class):
        _, mock_instance = mock_predictor_class
        mock_instance.model.config.id2label = {}

        from serving.inference_handler import InferenceHandler

        info = InferenceHandler("/models/trained_model").get_model_info()

        assert info["labels"] == []

    def test_model_info_when_not_ready(self):
        with patch(
            "serving.inference_handler.SentimentPredictor",
            side_effect=RuntimeError("no model"),
        ):
            from serving.inference_handler import InferenceHandler

            handler = InferenceHandler("/models/trained_model")

        info = handler.get_model_info()
        assert info["model_loaded"] is False
        assert "model_name" not in info
