"""Unit tests for text preprocessing module."""

import pytest

from src.preprocessing.text_cleaning import (
    clean_text,
    preprocess_batch,
    remove_stopwords,
    tokenize_simple,
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

    def test_clean_text_www_url_removal(self):
        """Unescaped dot in regex was matching unintended patterns — verify fix."""
        text = "Visit www.example.com for more info"
        cleaned = clean_text(text)
        assert "www" not in cleaned

    def test_clean_text_email_removal(self):
        text = "Contact us at support@example.com please"
        cleaned = clean_text(text)
        assert "@" not in cleaned

    def test_clean_text_no_lowercase(self):
        text = "Hello World"
        cleaned = clean_text(text, lowercase=False, remove_special=False)
        assert "Hello" in cleaned
        assert "World" in cleaned

    def test_tokenize_simple_multiple_spaces(self):
        tokens = tokenize_simple("hello   world")
        assert tokens == ["hello", "world"]

    def test_preprocess_batch(self):
        """Test batch preprocessing."""
        texts = ["Hello WORLD!", "Good Morning!"]
        processed = preprocess_batch(texts, clean=True)
        assert len(processed) == 2
        assert all(isinstance(text, str) for text in processed)

    def test_preprocess_batch_with_stopword_removal(self):
        pytest.importorskip("nltk")
        import nltk

        nltk.download("stopwords", quiet=True)
        texts = ["this is a great product", "it was really bad"]
        processed = preprocess_batch(texts, clean=True, remove_stops=True)
        assert len(processed) == 2
        assert all(isinstance(t, str) for t in processed)


class TestRemoveStopwords:
    def test_removes_common_words(self):
        pytest.importorskip("nltk")
        import nltk

        nltk.download("stopwords", quiet=True)
        tokens = ["this", "is", "a", "great", "product"]
        filtered = remove_stopwords(tokens)
        assert "this" not in filtered
        assert "great" in filtered

    def test_missing_nltk_raises_import_error(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "nltk.corpus":
                raise ImportError("no nltk")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", mock_import)
        with pytest.raises(ImportError):
            remove_stopwords(["hello", "world"])


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
