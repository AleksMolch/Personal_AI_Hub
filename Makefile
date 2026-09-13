# Makefile — единый интерфейс управления Personal AI Hub.
# Пользователь использует только эти команды; внутренние детали скрыты.

SHELL := /bin/bash
COMPOSE := docker compose
PYTHON := python3

.PHONY: help bootstrap up down status logs lint typecheck test test-unit test-integration test-e2e smoke backup restore migrate-check migrate health doctor

help: ## Список команд
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

## ---- Жизненный цикл стека -------------------------------------------------

bootstrap: ## Проверка окружения, генерация .env, сборка образов
	@infra/scripts/bootstrap.sh

up: ## Запуск стека (detached)
	@test -f .env || { echo "Сначала выполните: make bootstrap"; exit 1; }
	$(COMPOSE) up -d --build
	@echo "Жду готовности сервисов..."
	@$(COMPOSE) ps

down: ## Корректная остановка стека
	$(COMPOSE) down

status: ## Состояние контейнеров
	$(COMPOSE) ps

logs: ## Логи (используйте SERVICE=api/worker/web)
	$(COMPOSE) logs -f --tail=200 $(SERVICE)

health: ## Проверка health endpoints
	@infra/scripts/health.sh

doctor: ## Диагностика без вывода секретов
	@infra/scripts/doctor.sh

## ---- Качество кода ---------------------------------------------------------

lint: ## Ruff + ESLint + Prettier
	@docker run --rm -v "$$PWD":/work -w /work --entrypoint ruff ghcr.io/astral-sh/ruff:0.16.7 check apps/api packages/core
	@cd apps/web && npx eslint . && npx prettier --check .

typecheck: ## mypy + tsc
	@docker run --rm -v "$$PWD":/work -w /work \
		-e PYTHONPATH=/work/packages/core:/work/apps/api:/work/apps/worker \
		python:3.12-slim sh -c "pip install -q -r apps/api/requirements-dev.txt && mypy apps/api packages/core apps/worker"
	@cd apps/web && npx tsc --noEmit

## ---- Тесты -----------------------------------------------------------------

test-unit: ## Быстрые тесты без инфраструктуры
	@docker run --rm -v "$$PWD":/work -w /work \
		-e PYTHONPATH=/work/packages/core:/work/apps/api:/work/apps/worker \
		-e APP_MASTER_KEY=test_secret_key_32_bytes_minimum \
		python:3.12-slim sh -c "pip install -q -r apps/api/requirements-dev.txt && pytest tests/unit -q"

test-integration: ## Интеграционные тесты (изолированная инфраструктура)
	@docker compose build api
	@docker compose -f compose.yaml -f infra/compose/test.yaml run --rm test

test-e2e: ## E2E Playwright
	@cd apps/web && pnpm exec playwright test

test: ## Все бесплатные тесты
	$(MAKE) test-unit
	$(MAKE) test-integration

smoke: ## Smoke-тест поднятого экземпляра
	@infra/scripts/smoke.sh

## ---- Данные ----------------------------------------------------------------

backup: ## Создание резервной копии
	@infra/scripts/backup.sh

restore: ## Восстановление из резервной копии (FILE=путь)
	@infra/scripts/restore.sh "$(FILE)"

restore-verify: ## Проверка архива без изменения данных (FILE=путь)
	@infra/scripts/restore.sh --verify "$(FILE)"

## ---- Миграции --------------------------------------------------------------

migrate-check: ## Проверка миграций без применения
	@$(COMPOSE) run --rm --entrypoint alembic api check

migrate: ## Применение миграций
	@$(COMPOSE) run --rm --entrypoint alembic api upgrade head
