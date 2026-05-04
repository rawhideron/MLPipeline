"""Model inference utilities."""

import logging
from typing import List, Dict

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

logger = logging.getLogger(__name__)


class SentimentPredictor:
    """Predict sentiment using fine-tuned BERT model."""

    def __init__(self, model_path: str):
        """
        Load model for inference.

        Args:
            model_path: Path to saved model
        """
        self.model_path = model_path
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        logger.info(f"Loading model from {model_path}")
        self.model = AutoModelForSequenceClassification.from_pretrained(model_path).to(
            self.device
        )
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.model.eval()

        self.labels = {0: "negative", 1: "positive"}

    def predict(self, text: str) -> Dict:
        """
        Predict sentiment for a single text.

        Args:
            text: Input text

        Returns:
            Dictionary with prediction and confidence
        """
        inputs = self.tokenizer(
            text, padding=True, truncation=True, max_length=512, return_tensors="pt"
        ).to(self.device)

        with torch.no_grad():
            outputs = self.model(**inputs)

        logits = outputs.logits
        probabilities = torch.softmax(logits, dim=-1)
        prediction = torch.argmax(logits, dim=-1).item()
        confidence = probabilities[0][prediction].item()

        return {
            "text": text,
            "label": self.labels[prediction],
            "confidence": confidence,
            "probabilities": {
                "negative": float(probabilities[0][0]),
                "positive": float(probabilities[0][1]),
            },
        }

    def predict_batch(self, texts: List[str]) -> List[Dict]:
        """
        Predict sentiment for multiple texts in a single forward pass.

        Args:
            texts: List of input texts

        Returns:
            List of predictions
        """
        inputs = self.tokenizer(
            texts, padding=True, truncation=True, max_length=512, return_tensors="pt"
        ).to(self.device)

        with torch.no_grad():
            outputs = self.model(**inputs)

        logits = outputs.logits
        probabilities = torch.softmax(logits, dim=-1)
        predictions = torch.argmax(logits, dim=-1).tolist()

        return [
            {
                "text": text,
                "label": self.labels[pred],
                "confidence": float(probabilities[i][pred]),
                "probabilities": {
                    "negative": float(probabilities[i][0]),
                    "positive": float(probabilities[i][1]),
                },
            }
            for i, (text, pred) in enumerate(zip(texts, predictions))
        ]


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    model_path = sys.argv[1] if len(sys.argv) > 1 else "models/trained_model"

    predictor = SentimentPredictor(model_path)

    # Example predictions
    test_texts = [
        "This movie was absolutely fantastic!",
        "I was really disappointed with this film.",
        "It was okay, nothing special.",
    ]

    print("\nMaking predictions:")
    for result in predictor.predict_batch(test_texts):
        print(f"Text: {result['text']}")
        print(f"Sentiment: {result['label']} (confidence: {result['confidence']:.2%})")
        print()
