"""Model evaluation utilities."""

import json
import logging
from pathlib import Path
from typing import Dict

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer
from sklearn.metrics import (
    accuracy_score,
    precision_score,
    recall_score,
    f1_score,
    confusion_matrix,
)
import numpy as np

logger = logging.getLogger(__name__)


class ModelEvaluator:
    """Evaluate sentiment classification models."""

    def __init__(self, model_path: str):
        """
        Initialize evaluator with trained model.

        Args:
            model_path: Path to saved model
        """
        self.model_path = model_path
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        self.model = AutoModelForSequenceClassification.from_pretrained(model_path).to(
            self.device
        )
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.model.eval()

    def predict_batch(self, texts: list) -> Dict:
        """
        Get predictions for a batch of texts.

        Args:
            texts: List of input texts

        Returns:
            Dictionary with predictions and probabilities
        """
        inputs = self.tokenizer(
            texts, padding=True, truncation=True, max_length=512, return_tensors="pt"
        ).to(self.device)

        with torch.no_grad():
            outputs = self.model(**inputs)

        logits = outputs.logits
        predictions = torch.argmax(logits, dim=-1)
        probabilities = torch.softmax(logits, dim=-1)

        return {
            "predictions": predictions.cpu().numpy(),
            "probabilities": probabilities.cpu().numpy(),
            "logits": logits.cpu().numpy(),
        }

    def evaluate(self, test_dataset) -> Dict:
        """
        Evaluate model on test dataset.

        Args:
            test_dataset: Test dataset

        Returns:
            Dictionary with evaluation metrics
        """
        all_predictions = []
        all_labels = []

        for batch in test_dataset:
            texts = batch["text"]
            labels = batch["label"]

            results = self.predict_batch(texts)
            all_predictions.extend(results["predictions"])
            all_labels.extend(labels)

        all_predictions = np.array(all_predictions)
        all_labels = np.array(all_labels)

        metrics = {
            "accuracy": float(accuracy_score(all_labels, all_predictions)),
            "precision": float(
                precision_score(all_labels, all_predictions, average="weighted")
            ),
            "recall": float(
                recall_score(all_labels, all_predictions, average="weighted")
            ),
            "f1": float(f1_score(all_labels, all_predictions, average="weighted")),
            "confusion_matrix": confusion_matrix(all_labels, all_predictions).tolist(),
        }

        logger.info(f"Evaluation metrics: {metrics}")
        return metrics

    def save_metrics(self, metrics: Dict, output_path: str):
        """Save evaluation metrics to file."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, "w") as f:
            json.dump(metrics, f, indent=2)

        logger.info(f"Metrics saved to {output_path}")


if __name__ == "__main__":
    import sys
    from datasets import load_dataset

    logging.basicConfig(level=logging.INFO)

    model_path = sys.argv[1] if len(sys.argv) > 1 else "models/trained_model"
    metrics_path = sys.argv[2] if len(sys.argv) > 2 else "/models/metrics.json"
    accuracy_threshold = float(sys.argv[3]) if len(sys.argv) > 3 else 0.85

    evaluator = ModelEvaluator(model_path)
    logger.info("Model loaded from %s", model_path)

    test_dataset = load_dataset("imdb", split="test[:1000]")
    metrics = evaluator.evaluate(test_dataset.iter(batch_size=32))
    evaluator.save_metrics(metrics, metrics_path)

    accuracy = metrics["accuracy"]
    logger.info("Accuracy: %.4f (threshold: %.2f)", accuracy, accuracy_threshold)
    if accuracy < accuracy_threshold:
        raise SystemExit(
            f"Accuracy {accuracy:.4f} below threshold {accuracy_threshold} — deployment blocked"
        )
