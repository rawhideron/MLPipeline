"""FastAPI application for model serving with Keycloak OAuth."""

import logging
import os

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, field_validator
from typing import Annotated, Dict, List

from oauth_middleware import verify_token
from inference_handler import InferenceHandler

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="MLPipeline API",
    description="NLP Sentiment Classification Service",
    version="1.0.0",
    docs_url=None,
)


def _setup_tracing() -> None:
    node_ip = os.getenv("NODE_IP")
    if not node_ip:
        logger.info("NODE_IP not set — tracing disabled")
        return

    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource = Resource.create({SERVICE_NAME: "mlpipeline-serving"})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"http://{node_ip}:4317", insecure=True)
        )
    )
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    logger.info("Tracing enabled → %s:4317", node_ip)


_setup_tracing()


@app.get("/docs", include_in_schema=False, response_class=HTMLResponse)
async def custom_docs():
    # Swagger UI must fetch the spec through /api/openapi.json so nginx rewrites it correctly
    return get_swagger_ui_html(openapi_url="/api/openapi.json", title="MLPipeline API")


# Initialize model inference handler
inference_handler = InferenceHandler(model_path="/models/trained_model")


# Request/Response models
class PredictionRequest(BaseModel):
    """Request model for prediction."""

    text: str


class PredictionResponse(BaseModel):
    """Response model for prediction."""

    label: str
    confidence: float
    probabilities: Dict[str, float]


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    model_loaded: bool
    version: str


# Health check endpoint (no auth required)
@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy", model_loaded=inference_handler.is_ready(), version="1.0.0"
    )


# Prediction endpoint (OAuth protected)
TokenDep = Annotated[dict, Depends(verify_token)]


@app.post("/predict", response_model=PredictionResponse)
async def predict(request: PredictionRequest, token: TokenDep):
    """
    Predict sentiment for input text.

    Requires valid Keycloak OAuth token.
    """
    try:
        result = inference_handler.predict(request.text)
        return PredictionResponse(
            label=result["label"],
            confidence=result["confidence"],
            probabilities=result["probabilities"],
        )
    except Exception as e:
        logger.error("Prediction error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Prediction failed",
        )


class BatchPredictionRequest(BaseModel):
    """Request model for batch prediction."""

    texts: List[str]

    @field_validator("texts")
    @classmethod
    def texts_must_be_non_empty(cls, v: List[str]) -> List[str]:
        if not v:
            raise ValueError("texts list must not be empty")
        if len(v) > 100:
            raise ValueError("texts list must not exceed 100 items")
        return v


# Batch prediction endpoint (OAuth protected)
@app.post("/predict-batch")
async def predict_batch(request: BatchPredictionRequest, token: TokenDep):
    """
    Batch prediction endpoint.

    Requires valid Keycloak OAuth token.
    """
    try:
        results = inference_handler.predict_batch(request.texts)
        return {"predictions": results}
    except Exception as e:
        logger.error("Batch prediction error: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Batch prediction failed",
        )


# Model info endpoint
@app.get("/models")
async def get_model_info(token: TokenDep):
    """Get information about loaded model."""
    return inference_handler.get_model_info()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
