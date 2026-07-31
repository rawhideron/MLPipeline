"""Unit tests for FastAPI application."""

import sys
from unittest.mock import MagicMock, patch

import pytest
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
    handler.predict_batch.return_value = [
        {
            "label": "positive",
            "confidence": 0.95,
            "probabilities": {"negative": 0.05, "positive": 0.95},
        },
        {
            "label": "negative",
            "confidence": 0.88,
            "probabilities": {"negative": 0.88, "positive": 0.12},
        },
    ]
    handler.get_model_info.return_value = {
        "model_path": "/models/trained_model",
        "model_loaded": True,
        "model_name": "distilbert-base-uncased",
        "task": "sentiment-classification",
        "num_labels": 2,
        "labels": ["negative", "positive"],
    }
    return handler


@pytest.fixture
def app_with_mocks(mock_inference_handler):
    """FastAPI app with mocked inference handler."""
    with patch("serving.app.inference_handler", mock_inference_handler):
        from serving.app import app

        yield app


@pytest.fixture
def client(app_with_mocks):
    """Unauthenticated test client."""
    return TestClient(app_with_mocks)


@pytest.fixture
def authed_client(app_with_mocks):
    """Test client with auth dependency overridden.

    conftest.py puts serving/ on sys.path so `oauth_middleware` resolves to
    the same module object that app.py imports from (not serving.oauth_middleware).
    """
    import oauth_middleware

    app_with_mocks.dependency_overrides[oauth_middleware.verify_token] = lambda: {
        "sub": "test-user",
        "preferred_username": "testuser",
    }
    yield TestClient(app_with_mocks)
    app_with_mocks.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["model_loaded"] is True
        assert data["version"] == "1.0.0"

    def test_health_check_model_not_loaded(
        self, mock_inference_handler, app_with_mocks
    ):
        mock_inference_handler.is_ready.return_value = False
        c = TestClient(app_with_mocks)
        response = c.get("/health")
        assert response.status_code == 200
        assert response.json()["model_loaded"] is False


# ---------------------------------------------------------------------------
# Docs endpoint
# ---------------------------------------------------------------------------


class TestDocs:
    def test_docs_returns_html(self, client):
        response = client.get("/docs")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]


# ---------------------------------------------------------------------------
# Prediction endpoint (auth required)
# ---------------------------------------------------------------------------


class TestPredictionEndpoint:
    def test_predict_without_auth_fails(self, client):
        response = client.post("/predict", json={"text": "This is great!"})
        assert response.status_code in [401, 403]

    def test_predict_request_validation_missing_field(self, client):
        response = client.post("/predict", json={})
        assert response.status_code in [400, 401, 403, 422]

    def test_predict_success(self, authed_client):
        response = authed_client.post("/predict", json={"text": "Loved it!"})
        assert response.status_code == 200
        data = response.json()
        assert data["label"] == "positive"
        assert data["confidence"] == pytest.approx(0.95)
        assert "probabilities" in data

    def test_predict_error_hides_exception_details(
        self, authed_client, mock_inference_handler
    ):
        mock_inference_handler.predict.side_effect = RuntimeError(
            "secret internal path /etc/passwd"
        )
        response = authed_client.post("/predict", json={"text": "test"})
        assert response.status_code == 500
        assert "secret internal path" not in response.text
        assert "Prediction failed" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Batch prediction endpoint (auth required)
# ---------------------------------------------------------------------------


class TestBatchPredictionEndpoint:
    def test_batch_without_auth_fails(self, client):
        response = client.post("/predict-batch", json={"texts": ["hello"]})
        assert response.status_code in [401, 403]

    def test_batch_success(self, authed_client):
        response = authed_client.post(
            "/predict-batch", json={"texts": ["Great!", "Terrible."]}
        )
        assert response.status_code == 200
        data = response.json()
        assert "predictions" in data
        assert len(data["predictions"]) == 2

    def test_batch_empty_texts_fails_validation(self, authed_client):
        response = authed_client.post("/predict-batch", json={"texts": []})
        assert response.status_code == 422

    def test_batch_too_many_texts_fails_validation(self, authed_client):
        response = authed_client.post("/predict-batch", json={"texts": ["t"] * 101})
        assert response.status_code == 422

    def test_batch_error_hides_exception_details(
        self, authed_client, mock_inference_handler
    ):
        mock_inference_handler.predict_batch.side_effect = RuntimeError(
            "internal db uri leaked"
        )
        response = authed_client.post("/predict-batch", json={"texts": ["anything"]})
        assert response.status_code == 500
        assert "internal db uri" not in response.text
        assert "Batch prediction failed" in response.json()["detail"]


# ---------------------------------------------------------------------------
# Model info endpoint (auth required)
# ---------------------------------------------------------------------------


class TestModelInfo:
    def test_model_info_without_auth_fails(self, client):
        response = client.get("/models")
        assert response.status_code in [401, 403]

    def test_model_info_returns_metadata(self, authed_client):
        response = authed_client.get("/models")
        assert response.status_code == 200
        data = response.json()
        assert data["model_loaded"] is True
        assert "model_name" in data
        assert "num_labels" in data


# ---------------------------------------------------------------------------
# BatchPredictionRequest model validation (unit level)
# ---------------------------------------------------------------------------


class TestBatchPredictionRequestModel:
    def test_valid_list_accepted(self):
        from serving.app import BatchPredictionRequest

        req = BatchPredictionRequest(texts=["hello", "world"])
        assert len(req.texts) == 2

    def test_empty_list_raises(self):
        from pydantic import ValidationError

        from serving.app import BatchPredictionRequest

        with pytest.raises(ValidationError):
            BatchPredictionRequest(texts=[])

    def test_over_100_items_raises(self):
        from pydantic import ValidationError

        from serving.app import BatchPredictionRequest

        with pytest.raises(ValidationError):
            BatchPredictionRequest(texts=["x"] * 101)

    def test_exactly_100_items_accepted(self):
        from serving.app import BatchPredictionRequest

        req = BatchPredictionRequest(texts=["x"] * 100)
        assert len(req.texts) == 100


# ---------------------------------------------------------------------------
# Application structure
# ---------------------------------------------------------------------------


class TestAPIStructure:
    def test_app_initialization(self, app_with_mocks):
        assert app_with_mocks.title == "MLPipeline API"
        assert app_with_mocks.version == "1.0.0"

    def test_required_endpoints_defined(self, app_with_mocks):
        routes = [route.path for route in app_with_mocks.routes]
        assert "/health" in routes
        assert "/predict" in routes
        assert "/predict-batch" in routes
        assert "/models" in routes


# ---------------------------------------------------------------------------
# Tracing setup
# ---------------------------------------------------------------------------


class TestTracingSetup:
    def test_setup_tracing_when_node_ip_set(self, monkeypatch):
        monkeypatch.setenv("NODE_IP", "10.0.0.1")

        mock_sdk_resources = MagicMock()
        mock_sdk_resources.SERVICE_NAME = "service.name"

        otel_modules = {
            "opentelemetry": MagicMock(),
            "opentelemetry.trace": MagicMock(),
            "opentelemetry.exporter": MagicMock(),
            "opentelemetry.exporter.otlp": MagicMock(),
            "opentelemetry.exporter.otlp.proto": MagicMock(),
            "opentelemetry.exporter.otlp.proto.grpc": MagicMock(),
            "opentelemetry.exporter.otlp.proto.grpc.trace_exporter": MagicMock(),
            "opentelemetry.instrumentation": MagicMock(),
            "opentelemetry.instrumentation.fastapi": MagicMock(),
            "opentelemetry.sdk": MagicMock(),
            "opentelemetry.sdk.resources": mock_sdk_resources,
            "opentelemetry.sdk.trace": MagicMock(),
            "opentelemetry.sdk.trace.export": MagicMock(),
        }

        with patch.dict(sys.modules, otel_modules):
            from serving.app import _setup_tracing

            _setup_tracing()

    def test_setup_tracing_skipped_without_node_ip(self, monkeypatch):
        monkeypatch.delenv("NODE_IP", raising=False)

        from serving.app import _setup_tracing

        _setup_tracing()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
