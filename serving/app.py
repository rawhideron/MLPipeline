"""FastAPI application for model serving with Keycloak OAuth."""

import logging

from fastapi import FastAPI, HTTPException, Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

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
    root_path="/api",
)

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
    probabilities: dict


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
@app.post("/predict", response_model=PredictionResponse)
async def predict(request: PredictionRequest, token: dict = Depends(verify_token)):
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
        logger.error(f"Prediction error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Prediction failed: {str(e)}",
        )


# Batch prediction endpoint (OAuth protected)
@app.post("/predict-batch")
async def predict_batch(texts: list, token: dict = Depends(verify_token)):
    """
    Batch prediction endpoint.

    Requires valid Keycloak OAuth token.
    """
    try:
        results = inference_handler.predict_batch(texts)
        return {"predictions": results}
    except Exception as e:
        logger.error(f"Batch prediction error: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Batch prediction failed: {str(e)}",
        )


# Model info endpoint
@app.get("/models")
async def get_model_info(token: dict = Depends(verify_token)):
    """Get information about loaded model."""
    return inference_handler.get_model_info()


# Error handler
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Global HTTP exception handler."""
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
