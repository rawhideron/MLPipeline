"""Text preprocessing utilities for NLP pipeline."""

import re
import string
from typing import List, Optional


def clean_text(text: str, lowercase: bool = True, remove_special: bool = True) -> str:
    """
    Clean and normalize text.
    
    Args:
        text: Input text to clean
        lowercase: Convert to lowercase
        remove_special: Remove special characters
        
    Returns:
        Cleaned text
    """
    # Remove URLs
    text = re.sub(r'http\S+|www.\S+', '', text)
    
    # Remove HTML tags
    text = re.sub(r'<.*?>', '', text)
    
    # Remove email addresses
    text = re.sub(r'\S+@\S+', '', text)
    
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    
    if remove_special:
        # Remove punctuation
        text = text.translate(str.maketrans('', '', string.punctuation))
    
    if lowercase:
        text = text.lower()
    
    return text


def tokenize_simple(text: str) -> List[str]:
    """
    Simple whitespace tokenization.
    
    Args:
        text: Input text
        
    Returns:
        List of tokens
    """
    return text.split()


def remove_stopwords(tokens: List[str], language: str = "english") -> List[str]:
    """
    Remove common stopwords.
    
    Args:
        tokens: List of tokens
        language: Language for stopword removal
        
    Returns:
        Filtered tokens
    """
    try:
        from nltk.corpus import stopwords
    except ImportError:
        raise ImportError("NLTK required. Install with: pip install nltk")
    
    stop_words = set(stopwords.words(language))
    return [token for token in tokens if token.lower() not in stop_words]


def preprocess_batch(texts: List[str], clean: bool = True, 
                    remove_stops: bool = False) -> List[str]:
    """
    Preprocess a batch of texts.
    
    Args:
        texts: List of input texts
        clean: Apply text cleaning
        remove_stops: Remove stopwords
        
    Returns:
        Processed texts
    """
    processed = []
    for text in texts:
        if clean:
            text = clean_text(text)
        if remove_stops:
            tokens = tokenize_simple(text)
            tokens = remove_stopwords(tokens)
            text = ' '.join(tokens)
        processed.append(text)
    return processed


if __name__ == "__main__":
    # Example usage
    sample_texts = [
        "Check out this amazing product: https://example.com! #awesome",
        "I really enjoyed this! Great quality and fast shipping.",
        "This was disappointing... not as described."
    ]
    
    print("Original texts:")
    for text in sample_texts:
        print(f"  - {text}")
    
    print("\nCleaned texts:")
    cleaned = preprocess_batch(sample_texts, clean=True)
    for text in cleaned:
        print(f"  - {text}")
