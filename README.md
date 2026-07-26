# review_ducktective

Платформа автоматического code review на LLM: принимает дифф, возвращает находки,
привязанные к строкам кода, разложенные по уровням критичности и подтверждённые
цитатами из реального кода.

Работает в том числе полностью офлайн — кодовая база не покидает машину.

## Возможности

- **Ревью диффа** — параллельные специализированные проверки (корректность,
  безопасность, производительность, конвенции проекта) с верификацией находок.
- **RAG по кодовой базе** — AST-чанкинг через tree-sitter, граф символов,
  гибридный поиск (векторный + лексический) с реранкингом.
- **Diff-first retrieval** — контекст собирается от изменённого символа: что он
  вызывает и кто вызывает его. Модель видит последствия изменения, а не только дифф.
- **Чат по проекту** — вопросы в свободной форме со стримингом через WebSocket.
- **MCP-сервер** — инструменты навигации по коду для внешних агентов.
- **Air-gapped режим** — локальные модели через Ollama, ни одного запроса наружу.

## Стек

Python 3.12, FastAPI, LangGraph, SQLAlchemy 2.0 (async), PostgreSQL 17 + pgvector,
Redis, arq, LiteLLM, tree-sitter, React + TypeScript.

## Требования

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker и Docker Compose

## Быстрый старт

```bash
uv sync --all-packages

cp .env.example .env

docker compose --env-file .env -f deploy/compose/docker-compose.dev.yml up -d

uv run alembic upgrade head

uv run ducktective serve --reload
```

Проверка: http://localhost:8000/health, документация API: http://localhost:8000/docs

## Миграции

```bash
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "описание"
uv run alembic downgrade -1
```

Alembic читает `DATABASE_URL` из окружения — переменную нужно экспортировать
или запускать команды через `uv run --env-file .env`.

## Разработка

```bash
uv run pre-commit install --install-hooks
uv run pre-commit install --hook-type commit-msg   # проверка конвенции коммитов
uv run pytest                 # все тесты
uv run pytest -m "not integration"   # без контейнеров, быстро
uv run mypy .                 # типы
uv run lint-imports           # проверка границ слоёв
```

Форматирование — строго в этом порядке, isort первым:

```bash
uv run isort . && uv run ruff format . && uv run ruff check --fix .
```

Импорты оформляются по одному имени на строку в скобках (`force_grid_wrap = 1`).
Правило `I` в ruff сознательно отключено: ruff не поддерживает такой стиль,
за сортировку отвечает isort.

Коммиты — [Conventional Commits](https://www.conventionalcommits.org/), версия и
CHANGELOG формируются автоматически.

## Архитектура

Слоистый DDD: `apps` → `application` → `core` (домен). Инфраструктура реализует порты
домена. Доступ к данным — через репозитории агрегатов, границы транзакций — явный
Unit of Work. Правило зависимостей проверяется `import-linter` в CI.

```
packages/core          домен: агрегаты, value objects, события, порты
packages/application   use cases, границы транзакций
packages/storage       SQLAlchemy, репозитории, UnitOfWork, миграции
packages/indexing      tree-sitter, чанкинг, граф символов, эмбеддинги
packages/retrieval     гибридный поиск, реранкинг, diff-first retriever
packages/llm           LiteLLM, ModelRouter, кэш, structured output
packages/review_graph  узлы LangGraph и сборка графа
apps/api               FastAPI: REST + WebSocket
apps/indexer           воркер индексации
apps/reviewer          воркер ревью
```

Решения уровня кода — в `docs/adr/`.

## Лицензия

MIT
