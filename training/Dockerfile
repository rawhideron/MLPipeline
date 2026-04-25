FROM python:3.11-slim

WORKDIR /app

COPY training/requirements.txt .
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cpu \
    --extra-index-url https://pypi.org/simple \
    -r requirements.txt

COPY src/ /app/src/
COPY configs/ /app/configs/

RUN groupadd -r appuser && useradd -r -g appuser appuser \
    && chown -R appuser:appuser /app

USER appuser
