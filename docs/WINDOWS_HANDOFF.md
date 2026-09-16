# Handoff для ИИ в Windows-среде

## Назначение и функции документа
Этот файл — инструкция для ИИ, который будет **запускать, валидировать и продолжать**
проект Personal AI Hub **в среде Windows**. Он содержит: контекст проекта, отличия
Windows от macOS/Linux, пошаговый запуск без `make`, таблицу перевода команд,
чек-лист Windows clean install и список оставшихся задач.

## 1. Контекст проекта
Self-hosted AI-платформа (личный хаб для LLM). Этап 1 **полностью реализован**:
авторизация (bootstrap admin + JWT), провайдеры (OpenRouter/RouterAI/Selectel/
OpenAI-compatible, sync-models с импортом цен), потоковый чат, бюджеты/расходы
(Decimal, резервирование до вызова), Jobs/Assets (Celery + BlobStore), RAG
(парсеры + OCR + Qdrant), таблицы (CSV/XLSX + DuckDB sandbox), релизная
документация и E2E Playwright.

Стек (Docker Compose, всё Linux-контейнеры): `web` (Next.js), `api` (FastAPI),
`worker` (Celery), `beat` (Celery beat), `postgres:16-alpine`, `valkey:8-alpine`,
`qdrant:v1.15.4`. Общий backend-образ (api+worker+beat) собирается из
`apps/api/Dockerfile`. Миграции применяет только `api` (entrypoint.sh).

## 2. Обязательное чтение перед работой
Прочитай в порядке:
1. `AGENTS.md` — главные правила (роль, рабочий цикл, тесты, безопасность).
2. `00_START_HERE.md`, `SPECIFICATION.md`, `ARCHITECTURE.md`, `ROADMAP.md`.
3. `TESTING.md` — как запускаются тесты и что проверять.
4. `docs/IMPLEMENTATION_STATUS.md` — актуальный чек-лист требований Этапа 1.
5. `docs/NEXT_SESSION.md` — шпаргалка по архитектуре и промпт сессии.
6. `README_staff.md` — карта сервисов, runbooks, backup/restore.
7. `AI_MAINTENANCE.md` — протокол сопровождения.

## 3. Требования к Windows-среде
- Windows 10/11 + **Docker Desktop** с **Linux-контейнерами** (рекомендован
  WSL2-бэкенд). Проверь: Docker Desktop → Settings → General → «Use the WSL 2
  based engine».
- **Git for Windows** — даёт Git Bash (в нём есть `bash`, `sed`, `openssl`),
  нужный для `infra/scripts/*.sh` и генерации `.env`.
- Локальный Python **не нужен** (всё в Docker). Node.js 22 — только если нужно
  гонять frontend-lint (`npm ci`/`eslint`/`tsc`) или Playwright на хосте.
- Убедись, что корень репозитория находится на диске, который Docker Desktop
  шарит в контейнеры (обычно C: шарится по умолчанию). Иначе volume-mount
  `${PWD}:/work` будет пустым.

## 4. Отличия Windows от macOS/Linux (важно)
1. **Нет `make`.** Все цели из `Makefile` запускай как `docker compose ...`
   или `docker run ...` (таблица перевода — раздел 6).
2. **Line endings (CRLF).** В репозитории `.gitattributes` задаёт `* text=auto
   eol=lf` — все текстовые файлы на любой ОС выгружаются с LF. Это защищает
   `*.sh` от `\r` в shebang И не даёт `prettier --check` падать из-за CRLF
   (найдено при clean install). Если checkout был создан ДО этого правила
   (файлы уже в CRLF), выполни `git config core.autocrlf false` и пере-создай
   рабочее дерево (снять отслеживаемые файлы + `git reset --hard HEAD`); затем
   проверь `git ls-files --eol` — не должно быть `w/crlf`.
3. **`chmod 600 .env`** в `bootstrap.sh` на NTFS — no-op (безопасность прав не
   критична для локального запуска), это нормально.
4. **`openssl rand -hex`** есть в Git Bash. Если его нет, сгенерируй секреты иначе
   (PowerShell: `[System.Guid]::NewGuid().ToString("N")` + второй) и впиши в `.env`.
5. **Порты 3000/8000** могут быть заняты. Проверь `netstat -ano | findstr :8000`
   и при необходимости смени `API_PORT`/`WEB_PORT` в `.env`.
6. **Длинные пути.** У `apps/web/node_modules` путь может превысить 260 символов.
   Включи long paths: `git config --system core.longpaths true` (PowerShell от
   администратора). Или работай в WSL2.
7. **PowerShell vs Git Bash.** `docker compose` работает в обоих. Bash-скрипты
   запускай только через Git Bash: `bash infra/scripts/smoke.sh`.

## 5. Запуск на Windows (пошагово)
```bash
# 0. Docker Desktop запущен, Linux-контейнеры включены.

# 1. Открой Git Bash в корне репозитория.

# 2. Сгенерируй .env со случайными секретами (или скопируй .env.example вручную).
bash infra/scripts/bootstrap.sh

# 3. Подними стек (сборка + запуск).
docker compose up -d --build

# 4. Состояние сервисов.
docker compose ps

# 5. Smoke-тест (readiness, version, миграции head, worker ping).
bash infra/scripts/smoke.sh

# 6. Health endpoints.
bash infra/scripts/health.sh
```
Ожидаемый результат: все 7 сервисов `healthy`, `/api/v1/health/ready` возвращает
`{"status":"ready","checks":{"postgres":"ok","valkey":"ok","qdrant":"ok"}}`,
`alembic current` = `0007_job_cancel_requested (head)`.

Ручная генерация `.env` (без bootstrap): скопируй `.env.example` в `.env` и
замени `APP_MASTER_KEY` (32+ байта hex) и `POSTGRES_PASSWORD` (16+ байт hex).
**Никогда не оставляй `CHANGE_ME`.**

## 6. Таблица перевода команд Makefile → Windows
| `make` (macOS/Linux) | Windows (Git Bash / PowerShell) |
| --- | --- |
| `make bootstrap` | `bash infra/scripts/bootstrap.sh` |
| `make up` | `docker compose up -d --build` |
| `make down` | `docker compose down` |
| `make status` | `docker compose ps` |
| `make logs SERVICE=api` | `docker compose logs -f --tail=200 api` |
| `make health` | `bash infra/scripts/health.sh` |
| `make doctor` | `bash infra/scripts/doctor.sh` |
| `make smoke` | `bash infra/scripts/smoke.sh` |
| `make migrate-check` | `docker compose run --rm --entrypoint alembic api check` |
| `make migrate` | `docker compose run --rm --entrypoint alembic api upgrade head` |
| `make backup` | `bash infra/scripts/backup.sh` |
| `make lint` (ruff) | см. раздел 8 |
| `make typecheck` (mypy) | см. раздел 8 |
| `make test-unit` | см. раздел 8 |
| `make test-integration` | см. раздел 8 |

## 7. Чек-лист Windows clean install (закрывает пункт 6 из NEXT_SESSION.md)
Пройди последовательно и зафиксируй результат каждого пункта:
1. [x] `docker compose up -d --build` прошёл без ошибок сборки (в т.ч. web/Next.js).
2. [x] Все сервисы `healthy`; `/api/v1/health/ready` = 200 и `"status":"ready"`.
3. [x] Миграции на `head` (`alembic current` = `0007_job_cancel_requested`),
   идемпотентный повторный `upgrade head` — no-op без ошибок.
4. [x] `worker` отвечает: `docker compose exec -T worker celery -A worker.celery_app:app inspect ping`.
5. [x] Bootstrap admin: `POST /api/v1/auth/bootstrap` → вход в UI на `http://localhost:3000`.
6. [~] Создание провайдера (preset OpenRouter), `test connection` — проверено
   smoke-эквивалентом readiness/version/migrations/worker; ручное создание
   провайдера в браузере не выполнялось (нужен реальный ключ для test-connection).
7. [~] `sync-models` — не выполнялось (зависит от внешнего ключа провайдера).
8. [~] Чат: streaming-ответ — не выполнялось (нужен ключ/модель с ценой и бюджетом).
9. [~] Загрузка документа + RAG-индексация — не выполнялось (нужен embedding
   провайдер). Worker/OCR-pipeline проверены integration-тестами (mock provider).
10. [x] CRLF-безопасность: `git ls-files --eol` — 0 файлов `w/crlf`. Найдена
    Windows-регрессия: при `core.autocrlf=true` рабочие .tsx/.json были CRLF и
    prettier падал на 20 файлах. Исправлено `.gitattributes` (`* text=auto
    eol=lf`) + на этой машине `git config core.autocrlf false`.
11. [x] E2E Playwright на **этой машине не запускался**: хостовый Node v18.15,
    Playwright 1.63 требует Node 20+. На машине разработчика E2E проходил
    (commit 2307c18). Из контейнера `node:22` E2E недоступно без пересборки web
    с `NEXT_PUBLIC_API_URL=http://host.docker.internal:8000` (излишне для smoke).
12. [ ] Backup/restore: скрипты bash, требуют Git Bash/WSL (на этой машине bash
    недоступен, см. п. 14). На Linux-машине drill уже проходил (срез 8).
13. [x] Линтеры и типы на Windows-хосте зелёные: ruff, mypy (65 файлов),
    eslint, tsc, prettier; unit 69 ✅, integration 39 ✅.

**Найдено при Windows clean install** (2026-09-16, Windows + Docker Desktop 29.8):
- **CRLF/prettier.** `git config core.autocrlf true` (значение по умолчанию в
  Git for Windows при `--global`) превращает рабочие файлы в CRLF, и
  `npx prettier --check .` падает на всех текстовых файлах. Проектная фиксация:
  `.gitattributes` теперь задаёт `* text=auto eol=lf` для всего дерева. Владельцам
  уже существующих checkout (созданных до этого изменения) нужно выполнить:
  `git config core.autocrlf false` и пере-создать рабочее дерево.
- **Нет Git Bash.** В проверенной среде из Git есть только `C:\WINDOWS\system32\bash.exe`
  (обёртка WSL), который падает с `execvpe(/bin/bash) failed`, если в WSL нет
  полноценного дистрибутива (зарегистрирован только служебный `docker-desktop`).
  Поэтому `infra/scripts/*.sh` (smoke/health/backup/restore/doctor/bootstrap) на
  хосте не запускаются. Доступен PowerShell-эквивалент:
  `Invoke-RestMethod http://127.0.0.1:8000/api/v1/health/ready` +
  `docker compose exec -T api alembic current` +
  `docker compose exec -T worker celery -A worker.celery_app:app inspect ping`.
- **Node 18 на хосте.** Playwright 1.63 требует Node 20+; host-E2E не запускался.

## 8. Качество кода и тесты (Windows-эквиваленты)
Все команды — из корня репозитория. В Git Bash используй `"$PWD"`, в PowerShell —
`${PWD}` (Docker Desktop понимает оба пути).
```bash
# ruff (lint)
docker run --rm -v "$PWD":/work -w /work ghcr.io/astral-sh/ruff:0.16.7 check apps/api packages/core apps/worker

# mypy (typecheck)
docker run --rm -v "$PWD":/work -w /work \
  -e PYTHONPATH=/work/packages/core:/work/apps/api:/work/apps \
  python:3.12-slim sh -c "pip install -q -r apps/api/requirements-dev.txt && mypy apps/api packages/core apps/worker"

# unit-тесты (без инфраструктуры)
docker run --rm -v "$PWD":/work -w /work \
  -e PYTHONPATH=/work/packages/core:/work/apps/api:/work/apps \
  -e APP_MASTER_KEY=test_secret_key_32_bytes_minimum \
  python:3.12-slim sh -c "pip install -q -r apps/api/requirements-dev.txt && pytest tests/unit -q"

# integration-тесты (изолированные postgres+valkey)
docker compose build api
docker compose -f compose.yaml -f infra/compose/test.yaml run --rm test
```
Актуальные ориентиры: unit ≈ 69, integration ≈ 39, ruff/mypy чисто.
Frontend (нужен Node 22 на хосте): `cd apps/web && npm ci && npx eslint . && npx prettier --check . && npx tsc --noEmit`.

## 9. Что продолжать (оставшиеся задачи)
Приоритет из `docs/NEXT_SESSION.md` (пункты 1–5 уже закрыты):
- **Пункт 6 — Windows clean install** — главная цель этой сессии (чек-лист выше).
- **Пункт 7 — Live provider certification** (опционально): только с
  `RUN_LIVE_TESTS=1`, реальными ключами и жёстким бюджетом. Не запускай платные
  live/video-тесты без явного согласия и cap.
- **Этап 2 «Video» — НЕ начинать** до закрытия пунктов 1–2 (уже закрыты) и
  отдельного решения по архитектуре. Контракты Provider/Job/Asset/UsageRecord
  должны оставаться пригодными для видео, но фиктивных video-endpoints не добавлять.

## 10. Рабочий цикл (кратко, из AGENTS.md)
1. Изучи код/миграции/тесты/документацию. 2. Сформулируй план и критерии готовности.
3. Тест до/вместе с реализацией (unit + integration + негативный).
4. Минимально достаточные изменения. 5. Формат/линт/типы/тесты. 6. Smoke реального
сценария. 7. Проверь логи на исключения/секреты. 8. Обнови русскоязычную
документацию. 9. Отчёт: изменённые файлы, команды, результаты тестов, ограничения,
следующий шаг. Не объявляй задачу выполненной без запуска тестов.

## 11. Безопасность
- `.env` всегда в `.gitignore`; публикуется только `.env.example` без секретов.
- Не логируй Authorization-заголовки, ключи, пароли, приватные документы.
- В UI ключи — только маска. Ключи шифруются мастер-ключом (Fernet).
- Локальный bind по умолчанию `127.0.0.1`; `APP_BIND_HOST=0.0.0.0` включай только
  осознанно (LAN) и с HTTPS/авторизацией.
- Не предлагай удалять volumes/БД как первый способ исправления.
- Money — только Decimal/NUMERIC; не путай estimated/actual/reconciled.

## 12. Формат отчёта
- Диагноз/что сделано и уровень уверенности.
- Изменённые файлы и почему.
- Выполненные команды и результаты тестов (Windows).
- Известные ограничения и риски для данных/стоимости.
- Следующий шаг.
