"""Unit tests for text preprocessing module."""

import pytest
from src.preprocessing.text_cleaning import (
    clean_text,
    tokenize_simple,
    preprocess_batch,
)


class TestTextCleaning:
    """Test text cleaning functions."""

    def test_clean_text_basic(self):
        """Test basic text cleaning."""
        text = "Hello WORLD!"
        cleaned = clean_text(text, lowercase=True)
        assert cleaned == "hello world"

    def test_clean_text_url_removal(self):
        """Test URL removal."""
        text = "Check this https://example.com out!"
        cleaned = clean_text(text)
        assert "https" not in cleaned

    def test_clean_text_punctuation(self):
        """Test punctuation removal."""
        text = "Hello, world! How are you?"
        cleaned = clean_text(text, remove_special=True)
        assert "," not in cleaned
        assert "!" not in cleaned

    def test_tokenize_simple(self):
        """Test simple tokenization."""
        text = "Hello world"
        tokens = tokenize_simple(text)
        assert tokens == ["Hello", "world"]

    def test_preprocess_batch(self):
        """Test batch preprocessing."""
        texts = ["Hello WORLD!", "Good Morning!"]
        processed = preprocess_batch(texts, clean=True)
        assert len(processed) == 2
        assert all(isinstance(text, str) for text in processed)


class TestPreprocessingPipeline:
    """Test end-to-end preprocessing pipeline."""

    def test_full_pipeline(self):
        """Test complete preprocessing pipeline."""
        texts = [
            "Check out https://example.com! Amazing! 😊",
            "Not happy with this. Terrible!!",
            "It's average. Nothing special, really.",
        ]

        processed = preprocess_batch(texts, clean=True)

        assert len(processed) == len(texts)
        assert all(isinstance(text, str) for text in processed)
        assert all(text for text in processed)  # Not empty


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
