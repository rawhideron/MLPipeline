"""Inference handler for FastAPI serving."""

import logging
import sys

sys.path.insert(0, "/app")

from src.models.inference import SentimentPredictor

logger = logging.getLogger(__name__)


class InferenceHandler:
    """Manages model loading and inference requests."""

    def __init__(self, model_path: str = "/models/trained_model"):
        """
        Initialize inference handler with model.

        Args:
            model_path: Path to saved model
        """
        self.model_path = model_path
        self.model = None
        self.ready = False

        try:
            self.model = SentimentPredictor(model_path)
            self.ready = True
            logger.info(f"Model loaded successfully from {model_path}")
        # Any load failure should mark not-ready, not crash.
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to load model: {e!s}")
            self.ready = False

    def is_ready(self) -> bool:
        """Check if model is ready for inference."""
        return self.ready and self.model is not None

    def predict(self, text: str) -> dict:
        """
        Single text prediction.

        Args:
            text: Input text

        Returns:
            Prediction result
        """
        if not self.is_ready():
            raise RuntimeError("Model not ready for inference")

        return self.model.predict(text)

    def predict_batch(self, texts: list[str]) -> list[dict]:
        """
        Batch prediction.

        Args:
            texts: List of input texts

        Returns:
            List of predictions
        """
        if not self.is_ready():
            raise RuntimeError("Model not ready for inference")

        return self.model.predict_batch(texts)

    def get_model_info(self) -> dict:
        """Get information about loaded model."""
        info: dict = {
            "model_path": self.model_path,
            "model_loaded": self.is_ready(),
        }
        if self.is_ready():
            cfg = self.model.model.config
            info["model_name"] = cfg.name_or_path
            info["task"] = "sentiment-classification"
            info["num_labels"] = cfg.num_labels
            info["labels"] = list(cfg.id2label.values()) if cfg.id2label else []
        return info


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    handler = InferenceHandler()
    if handler.is_ready():
        result = handler.predict("This is a great product!")
        print(f"Prediction: {result}")
    else:
        print("Model not available")
