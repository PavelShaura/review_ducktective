# Конвенция коммитов

Conventional Commits. Проверяется хуком `commitizen` на `commit-msg`; на основе типов
формируются версия и CHANGELOG через `python-semantic-release`.

## Формат

```
<тип>(<область>): <описание>

[тело: что и почему, если неочевидно]

[футер: BREAKING CHANGE, ссылки]
```

## Типы

| Тип | Когда | Влияние на версию |
|---|---|---|
| `feat` | новая функциональность | minor |
| `fix` | исправление бага | patch |
| `perf` | оптимизация без изменения поведения | patch |
| `refactor` | рефакторинг без изменения поведения | — |
| `test` | тесты | — |
| `docs` | документация, ADR, комментарии | — |
| `build` | зависимости, сборка, Docker | — |
| `ci` | пайплайны, workflow | — |
| `chore` | вспомогательное: конфиги, скрипты, служебные файлы | — |
| `style` | форматирование без изменения смысла | — |

Ломающее изменение помечается `!` после области либо футером `BREAKING CHANGE:`
и поднимает мажорную версию:

```
feat(storage)!: replace snapshot identity with content hash
```

Типа `config` в стандарте нет — изменения конфигурации оформляются как
`chore(config): ...`.

## Области

**Область указывается всегда.** По истории должно быть видно, какой слой затронут,
без открытия диффа.

Пакеты и приложения:

`core`, `application`, `storage`, `indexing`, `retrieval`, `llm`, `review_graph`,
`vcs`, `analyzers`, `evals`, `observability`, `api`, `indexer`, `reviewer`,
`mcp`, `web`

Инфраструктурные области:

| Область | Что покрывает |
|---|---|
| `config` | конфигурация репозитория: `.gitignore`, `pyproject.toml`, настройки линтеров |
| `packaging` | сборка и дистрибуция пакетов, `py.typed`, точки входа |
| `deps` | зависимости и `uv.lock` |
| `deploy` | docker, compose, helm, k8s |
| `workflows` | GitHub Actions, pre-commit |
| `docs` | документация и ADR (как область, когда тип не `docs`) |
| `repo` | изменения, не сводимые ни к одной области выше |

Если изменение затрагивает несколько областей — это, как правило, признак того,
что коммит надо разбить.

## Правила

- Область в скобках обязательна: `fix(storage): ...`, а не `fix: ...`.
- Описание на английском, строчными буквами, без точки в конце.
- Повелительное наклонение: `add`, `fix`, `remove` — не `added`, не `adds`.
- Первая строка — до 72 символов.
- Один коммит — одно логическое изменение. Миграция схемы и использующий её код
  могут идти вместе; несвязанный рефакторинг — отдельно.
- Тело обязательно, если решение неочевидно: там объясняется **почему**, а не что.
- Изменение промпта требует в теле результатов eval-прогона (см. `08-conventions.md`
  в документах стратегии).

## Примеры

```
feat(storage): add unit of work with post-commit event publishing
feat(indexing): build symbol graph from tree-sitter ast
fix(retrieval): keep lexical hits when rrf scores tie
fix(config): stop gitignore from excluding storage models package
perf(indexing): reuse embeddings for chunks with unchanged content hash
refactor(core): move egress policy into value object
test(application): cover repository registration use case
docs(adr): record layered ddd decision
build(deps): add pgvector and asyncpg
ci(workflows): run isort check before ruff
chore(deploy): move host ports to environment variables
```

## Для агентов

Коммиты создаёт **пользователь**, не агент. Задача агента — по завершении работы
предложить готовое сообщение коммита в этом формате, одним блоком, чтобы его можно
было скопировать. Если изменения разнородны — предложить разбиение на несколько
коммитов с указанием, какие файлы входят в каждый.

Не добавлять в сообщение упоминания инструментов, которыми оно написано, эмодзи
и служебные подписи.
