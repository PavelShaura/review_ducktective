<p align="center">
  <img src="docs/logo/logo.png" alt="review_ducktective" width="320">
</p>

<h1 align="center">review_ducktective</h1>

<p align="center">
  <b>LLM-ревьюер. Видит всё. Цитирует код. Не крякает по пустякам.</b>
</p>

---

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

Фоновый воркер ревью (в отдельном терминале):

```bash
uv run arq ducktective.reviewer.worker.WorkerSettings
```

## Ревью из терминала

Автономный режим: без базы, без Redis, без запущенного API. Нужна только локальная
модель — код никуда не уходит.

```bash
# то, что собираешься коммитить
ducktective review --staged --no-store

# диапазон ревизий
ducktective review /path/to/repo --no-store --base HEAD~1 --head HEAD

# отчёт для описания pull request
ducktective review --staged --no-store --format markdown
```

Форматы вывода: `rich` (по умолчанию), `json`, `markdown`.

Большой коммит можно сузить до нужной части — `--include` принимает шаблоны
и повторяется несколько раз. `*` покрывает и разделители каталогов, поэтому
`src/report/*` найдёт файлы на любой глубине:

```bash
ducktective review /path/to/repo --no-store \
  --base a1b2c3d~1 --head a1b2c3d \
  --include 'src/report/*' --include '*.py'
```

С флагом `--fail-on` команда возвращает ненулевой код, если найдены проблемы
указанного уровня или выше — это делает её пригодной для git-хука и для CI:

```bash
ducktective review --staged --no-store --fail-on major
```

```yaml
# .pre-commit-config.yaml
- repo: local
  hooks:
    - id: ducktective
      name: ducktective
      entry: ducktective review --staged --no-store --fail-on critical
      language: system
      pass_filenames: false
```

Режим с хранением (без `--no-store`) пишет прогоны и находки в базу, требует
`--tenant` и поднятой инфраструктуры — он нужен, чтобы размечать находки
и накапливать данные для оценки качества.

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
