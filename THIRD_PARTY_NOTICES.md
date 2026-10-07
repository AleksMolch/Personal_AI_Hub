# Сторонние компоненты и лицензии

## Назначение и функции
Документ перечисляет ключевые сторонние зависимости и их лицензии.
Версии зафиксированы lock-файлами (`apps/api/requirements.txt`,
`apps/web/package-lock.json`) и конкретными тегами Docker-образов.

> Лицензии указаны по официальной документации проектов. Перед публичным
> релизом выполните финальную сверку с фактическими LICENSE-файлами
> установленных дистрибутивов (команда `make doctor` и CI secret/license scan).

## Backend (Python 3.12)

| Пакет | Версия | Лицензия |
| --- | --- | --- |
| fastapi | 0.141.1 | MIT |
| uvicorn | 0.52.4 | BSD-3-Clause |
| sqlalchemy | 2.0.52 | MIT |
| alembic | 1.20.0 | MIT |
| asyncpg | 0.31.0 | Apache-2.0 |
| greenlet | 3.5.5 | MIT |
| pydantic | 2.13.5 | MIT |
| pydantic-settings | 2.15.0 | MIT |
| httpx | 0.28.1 | BSD-3-Clause |
| celery | 5.6.3 | BSD-3-Clause |
| redis | 8.1.0 | MIT |
| cryptography | 50.0.1 | Apache-2.0 / BSD-3-Clause |
| python-multipart | 0.0.32 | Apache-2.0 |
| argon2-cffi | 25.1.0 | MIT |
| PyJWT | 2.14.0 | MIT |
| pypdf | 6.18.1 | BSD-3-Clause |
| python-docx | 1.2.0 | MIT |
| qdrant-client | 1.19.0 | Apache-2.0 |
| duckdb | 1.5.5 | MIT |
| openpyxl | 3.1.5 | MIT |
| pytesseract | 0.3.13 | Apache-2.0 |
| pdf2image | 1.17.0 | MIT |

Опциональный OCR-backend (НЕ входит в базовые зависимости): rapidocr_onnxruntime
(Apache-2.0) + onnxruntime (MIT, функционально включён в пакет RapidOCR).
Устанавливается отдельно при включении `OCR_BACKEND=rapidocr` (см. README_staff).

Транзитивные зависимости RapidOCR при headless-установке (см. README_staff):
opencv-python-headless (Apache-2.0), pyclipper (MIT), Shapely (BSD-3-Clause),
tqdm (MPL-2.0 + MIT). `opencv-python` (Apache-2.0) не используется: вместе с
ним требуется системный пакет `libgl1` (mesa, лицензия MIT), что увеличивает
образ примерно на 336 МБ.

Dev-инструменты: pytest (MIT), pytest-asyncio (Apache-2.0), ruff (MIT),
mypy (MIT).

Экспериментальный бенчмарк (`experiments/llamaindex_rag_benchmark/`, в поставку
не входит): llama-index-core 0.14.25 (MIT). Устанавливается только в
одноразовый контейнер эксперимента; в backend/web-образы и runtime не попадает
(ADR-0003).

## Frontend (Node.js)

| Пакет | Версия | Лицензия |
| --- | --- | --- |
| next | 16.3.5 | MIT |
| react | 19.3.0 | MIT |
| react-dom | 19.3.0 | MIT |
| typescript | 5.9.3 | Apache-2.0 |
| eslint | 9.39.5 | MIT |
| eslint-config-next | 16.3.5 | MIT |
| prettier | 3.9.6 | MIT |

## Образы инфраструктуры

| Образ | Тег | Лицензия |
| --- | --- | --- |
| postgres | 16-alpine | PostgreSQL License |
| valkey/valkey | 8-alpine | BSD-3-Clause |
| qdrant/qdrant | v1.15.4 | Apache-2.0 |
| python | 3.12-slim | PSF License |
| node | 22-alpine | MIT |

Опциональный сервис (compose-профиль `litellm`, ADR-0004): LiteLLM
(ghcr.io/berriai/litellm:v1.104.0, MIT). По умолчанию не запускается и не
скачивается; в backend-образе библиотека `litellm` отсутствует.

Системные пакеты OCR (в backend-образе): tesseract-ocr (Apache-2.0),
poppler-utils (GPL-2.0+).

## Инструменты CI

| Инструмент | Назначение | Лицензия |
| --- | --- | --- |
| gitleaks | secret scanning | MIT |
| ruff (ghcr.io/astral-sh/ruff) | lint | MIT |
