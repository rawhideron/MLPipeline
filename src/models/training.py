"""Model training for NLP sentiment classification."""

import logging
from pathlib import Path
from typing import Dict, Tuple

import torch
import yaml
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    Trainer,
    TrainingArguments,
    DataCollatorWithPadding,
)
from datasets import load_dataset, DatasetDict

logger = logging.getLogger(__name__)


class SentimentTrainer:
    """Train sentiment classification models using HuggingFace Transformers."""

    def __init__(self, config_path: str):
        """
        Initialize trainer with configuration.

        Args:
            config_path: Path to YAML configuration file
        """
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.model_name = self.config["model"]["name"]
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_name)
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Using device: {self.device}")

    def load_dataset(self) -> DatasetDict:
        """
        Load dataset from HuggingFace Datasets.

        Returns:
            DatasetDict with train/test splits
        """
        dataset_name = self.config["data"]["dataset"]
        logger.info(f"Loading dataset: {dataset_name}")

        # For this example, using IMDB movie reviews
        dataset = load_dataset("imdb")

        # Split into train/val/test
        val_split = self.config["data"]["validation_split"]
        test_split = self.config["data"]["test_split"]

        # Create validation and test sets from train set
        train = dataset["train"].train_test_split(test_size=(val_split + test_split))[
            "train"
        ]
        temp = dataset["train"].train_test_split(test_size=(val_split + test_split))[
            "test"
        ]
        val_test = temp.train_test_split(test_size=0.5)

        return DatasetDict(
            {"train": train, "validation": val_test["train"], "test": val_test["test"]}
        )

    def preprocess_function(self, examples):
        """Tokenize examples."""
        max_length = self.config["data"]["max_length"]
        return self.tokenizer(
            examples["text"],
            padding="max_length",
            max_length=max_length,
            truncation=True,
        )

    def prepare_dataset(self, dataset: DatasetDict) -> Tuple[any, any, any]:
        """
        Tokenize and prepare dataset.

        Args:
            dataset: Input dataset

        Returns:
            Tuple of (train, validation, test) datasets
        """
        logger.info("Preprocessing dataset...")

        tokenized = dataset.map(
            self.preprocess_function, batched=True, remove_columns=["text"]
        )

        tokenized = tokenized.rename_column("label", "labels")

        return (tokenized["train"], tokenized["validation"], tokenized["test"])

    def train(self) -> Dict:
        """
        Train the model.

        Returns:
            Dictionary with training results
        """
        # Load and prepare dataset
        dataset = self.load_dataset()
        train_data, val_data, test_data = self.prepare_dataset(dataset)

        # Load model
        logger.info(f"Loading model: {self.model_name}")
        model = AutoModelForSequenceClassification.from_pretrained(
            self.model_name, num_labels=self.config["model"]["num_labels"]
        ).to(self.device)

        # Training arguments
        output_dir = self.config["output"]["model_path"]
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        training_args = TrainingArguments(
            output_dir=output_dir,
            num_train_epochs=self.config["training"]["epochs"],
            per_device_train_batch_size=self.config["training"]["batch_size"],
            per_device_eval_batch_size=self.config["training"]["batch_size"],
            learning_rate=self.config["training"]["learning_rate"],
            weight_decay=self.config["training"]["weight_decay"],
            warmup_steps=self.config["training"]["warmup_steps"],
            logging_steps=100,
            save_steps=500,
            eval_strategy="epoch",
            save_strategy="epoch",
            load_best_model_at_end=True,
            metric_for_best_model="accuracy",
        )

        # Data collator
        data_collator = DataCollatorWithPadding(self.tokenizer)

        # Trainer
        trainer = Trainer(
            model=model,
            args=training_args,
            train_dataset=train_data,
            eval_dataset=val_data,
            data_collator=data_collator,
        )

        # Train
        logger.info("Starting training...")
        results = trainer.train()

        # Save model
        trainer.save_model(output_dir)
        self.tokenizer.save_pretrained(output_dir)

        logger.info(f"Model saved to {output_dir}")

        return {"train_loss": results.training_loss, "status": "completed"}


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    config_path = sys.argv[1] if len(sys.argv) > 1 else "configs/training_config.yaml"

    trainer = SentimentTrainer(config_path)
    results = trainer.train()
    print(f"Training results: {results}")
