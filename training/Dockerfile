FROM python:3.11-slim

WORKDIR /app

COPY training/requirements.txt .
RUN pip install --no-cache-dir \
    --index-url https://download.pytorch.org/whl/cu130 \
    --extra-index-url https://pypi.org/simple \
    -r requirements.txt

COPY src/ /app/src/
COPY configs/ /app/configs/

RUN groupadd -r appuser && useradd -r -m -g appuser appuser \
    && chown -R appuser:appuser /app /home/appuser

ENV HOME=/home/appuser

USER appuser
