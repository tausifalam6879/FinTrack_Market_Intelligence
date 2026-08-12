FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000 \
    APP_ENV=production \
    DATABASE_URL=sqlite:////app/data/fintrack.db \
    MODEL_ARTIFACT_DIR=/app/artifacts

WORKDIR /app
COPY requirements-runtime.txt .
RUN pip install --no-cache-dir -r requirements-runtime.txt \
    && groupadd --gid 10001 fintrack \
    && useradd --uid 10001 --gid fintrack --create-home --shell /usr/sbin/nologin fintrack

COPY --chown=fintrack:fintrack app.py runtime_health.py market_intelligence.py agent_orchestrator.py company_catalog.py persistence.py data_pipeline.py offline_training.py deep_learning.py experiment_tracking.py model_registry.py model_monitoring.py document_rag.py official_documents.py sec_filings.py ./
RUN mkdir -p /app/data /app/artifacts \
    && chown -R fintrack:fintrack /app

USER fintrack

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:' + __import__('os').environ.get('PORT', '8000') + '/health/ready', timeout=4)" || exit 1

CMD ["sh", "-c", "uvicorn app:app --host 0.0.0.0 --port ${PORT}"]
