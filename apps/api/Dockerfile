# Backend-образ Personal AI Hub (FastAPI + Celery worker).
# Один образ обслуживает сервисы api и worker: они различаются только командой.
# Контекст сборки — корень репозитория.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# OCR-зависимости: tesseract (eng+rus) и poppler (для рендера PDF-страниц).
# Ставим до pip-слоя, чтобы кэшировать отдельно.
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-rus \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Зависимости устанавливаются отдельным слоем для кэширования.
COPY apps/api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Общий доменный пакет и точки входа API/worker.
COPY packages/core/personal_hub /app/personal_hub
COPY apps/api/app /app/app
COPY apps/worker /app/worker
COPY apps/api/alembic.ini /app/alembic.ini
COPY apps/api/migrations /app/migrations
COPY apps/api/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

EXPOSE 8000

# CMD (а не ENTRYPOINT), чтобы worker мог переопределить команду на celery,
# не запуская миграции. api использует entrypoint.sh (миграции + uvicorn).
CMD ["/app/entrypoint.sh"]
