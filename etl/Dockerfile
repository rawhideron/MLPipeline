FROM python:3.11-slim

WORKDIR /app
ENV PYTHONPATH=/app

COPY etl/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ /app/src/
COPY configs/ /app/configs/

RUN groupadd -r appuser && useradd -r -g appuser appuser \
    && chown -R appuser:appuser /app

USER appuser
