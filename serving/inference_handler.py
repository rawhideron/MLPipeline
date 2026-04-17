"""Inference handler for FastAPI serving."""

import logging
from pathlib import Path
from typing import List, Dict, Optional

import sys
sys.path.insert(0, '/app')

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
        except Exception as e:
            logger.error(f"Failed to load model: {str(e)}")
            self.ready = False
    
    def is_ready(self) -> bool:
        """Check if model is ready for inference."""
        return self.ready and self.model is not None
    
    def predict(self, text: str) -> Dict:
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
    
    def predict_batch(self, texts: List[str]) -> List[Dict]:
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
    
    def get_model_info(self) -> Dict:
        """Get information about loaded model."""
        return {
            'model_path': self.model_path,
            'model_loaded': self.is_ready(),
            'model_name': 'distilbert-base-uncased',
            'task': 'sentiment-classification',
            'num_labels': 2,
            'labels': ['negative', 'positive']
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    handler = InferenceHandler()
    if handler.is_ready():
        result = handler.predict("This is a great product!")
        print(f"Prediction: {result}")
    else:
        print("Model not available")
