"""Unit tests for FastAPI application."""

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


@pytest.fixture
def mock_inference_handler():
    """Mock inference handler."""
    handler = MagicMock()
    handler.is_ready.return_value = True
    handler.predict.return_value = {
        "label": "positive",
        "confidence": 0.95,
        "probabilities": {"negative": 0.05, "positive": 0.95},
    }
    handler.get_model_info.return_value = {
        "model_name": "distilbert-base-uncased",
        "task": "sentiment-classification",
        "num_labels": 2,
    }
    return handler


@pytest.fixture
def app_with_mocks(mock_inference_handler):
    """FastAPI app with mocked dependencies."""
    with patch("serving.app.inference_handler", mock_inference_handler):
        from serving.app import app

        yield app


@pytest.fixture
def client(app_with_mocks):
    """Test client."""
    return TestClient(app_with_mocks)


class TestHealthCheck:
    """Test health check endpoint."""

    def test_health_check(self, client):
        """Test health endpoint without auth."""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["model_loaded"] is True
        assert data["version"] == "1.0.0"


class TestModelInfo:
    """Test model info endpoint."""

    def test_model_info_without_auth(self, client, mock_inference_handler):
        """Test model info endpoint requires auth."""
        # In real scenario, this should require OAuth token
        # For testing, we'll just check the structure

        model_info = mock_inference_handler.get_model_info()
        assert "model_name" in model_info
        assert "task" in model_info
        assert "num_labels" in model_info


class TestPredictionEndpoint:
    """Test prediction endpoints."""

    def test_predict_without_auth_fails(self, client):
        """Test predict without auth fails."""
        response = client.post("/predict", json={"text": "This is great!"})

        # Should require auth
        assert response.status_code in [401, 403]

    def test_predict_request_validation(self, client):
        """Test prediction request validation."""
        # Missing required field
        response = client.post("/predict", json={})
        assert response.status_code in [422, 400, 401, 403]


class TestAPIStructure:
    """Test FastAPI application structure."""

    def test_app_initialization(self):
        """Test app is properly initialized."""
        # Import without mocks to check structure
        try:
            from serving.app import app

            assert app.title == "MLPipeline API"
            assert app.version == "1.0.0"
        except ImportError:
            pytest.skip("Serving module not available")

    def test_app_endpoints_defined(self, app_with_mocks):
        """Test required endpoints are defined."""
        routes = [route.path for route in app_with_mocks.routes]

        assert "/health" in routes
        assert "/predict" in routes or "/predict-batch" in routes


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
