<p align="center">
  <img src="docs/logo/logo.png" alt="review_ducktective" width="320">
</p>

<h1 align="center">review_ducktective</h1>

<p align="center">
  <b>An LLM reviewer. Sees everything. Quotes your code. Doesn't quack over trifles.</b>
</p>

<p align="center">
  <a href="https://github.com/PavelShaura/review_ducktective/actions"><img src="https://github.com/PavelShaura/review_ducktective/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <img src="https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white" alt="Python 3.12">
  <img src="https://img.shields.io/badge/FastAPI-async-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/PostgreSQL-17%20%2B%20pgvector-336791?logo=postgresql&logoColor=white" alt="PostgreSQL + pgvector">
  <img src="https://img.shields.io/badge/100%25-offline%20capable-success?logo=ghostery&logoColor=white" alt="Offline capable">
  <br>
  <img src="https://img.shields.io/badge/linter-ruff-D7FF64?logo=ruff&logoColor=black" alt="Ruff">
  <img src="https://img.shields.io/badge/types-mypy-2A6DB2" alt="mypy">
  <img src="https://img.shields.io/badge/commits-conventional-FE5196?logo=conventionalcommits&logoColor=white" alt="Conventional Commits">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License: MIT">
</p>

---

An automated code review platform built on an LLM: it takes a diff, returns findings
tied to specific lines of code, sorted by severity and backed by quotes from the
real code.

It can run fully offline too — your codebase never leaves the machine.

## What it does

- **Diff review** — parallel, specialized passes (correctness, security,
  performance, project conventions) with a verification step on every finding.
- **RAG over the codebase** — AST chunking via tree-sitter, a symbol graph, and
  hybrid search (vector + lexical) with reranking.
- **Diff-first retrieval** — context is gathered starting from the changed symbol:
  what it calls, and who calls it. The model sees the fallout of a change, not just
  the diff.
- **Chat with your project** — ask anything in plain language, streamed over WebSocket.
- **MCP server** — lets external agents navigate the index: semantic search,
  definitions, call graph.
- **Air-gapped mode** — local models through Ollama, not a single request going out.

## Stack

Python 3.12, FastAPI, LangGraph, SQLAlchemy 2.0 (async), PostgreSQL 17 + pgvector,
Redis, arq, LiteLLM, tree-sitter, React + TypeScript.

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)
- Docker and Docker Compose

## Quick start

```bash
uv sync --all-packages

cp .env.example .env

docker compose --env-file .env -f deploy/compose/docker-compose.dev.yml up -d

uv run alembic upgrade head

uv run ducktective dev
```

One command brings up the API, both workers, and the frontend, merges their logs
into a single stream tagged by source, and shuts everyone down on Ctrl+C. The
processes stay separate, though — indexing and review have different load profiles
(D-013).

```bash
uv run ducktective dev --reload        # restart the API on changes
uv run ducktective dev --no-web        # without the frontend
uv run ducktective dev --no-workers    # API only
```

Or one at a time, when you want to watch just one of them:

```bash
uv run ducktective serve --reload
uv run arq ducktective.reviewer.worker.WorkerSettings   # review
uv run arq ducktective.indexer.worker.WorkerSettings    # indexing
```

## MCP server

Ducktective parses your codebase and builds a reference book out of it: where each
symbol starts and ends, who calls whom, which fragment is about what. The MCP server
opens that reference book up — Claude Code, Cursor, and other clients can look things
up in it.

Five tools:

| Tool | Answers the question |
|---|---|
| `list_repositories` | which codebases are indexed, and how fresh they are |
| `search_code` | where is this done — by meaning, not by literal text |
| `get_definition` | what does this symbol look like in full |
| `find_callers` | who calls it, i.e. what would break |
| `get_file_context` | what's going on at these lines of a file |

Where it shines is the connections `grep` chokes on: "who calls this," "where else
is this done," "what covers these lines." Same-named symbols all come back; graph
neighbors come back as a signature, without the body.

What it deliberately won't do: **git history** (branches, commits, authors — your
client already has `git log`), **the working copy** (answers describe a committed
revision; mixing in half-written code would stop the index from being trustworthy),
and **review runs** (findings, severity, and marks live in other tables — this
server doesn't read them).

Every answer is stamped with the index revision and build date, so you can tell how
fresh it is. After commits, the index gets rebuilt — `ducktective index .`.

The default transport is stdio — the client starts the server itself. That makes the
client's directory the working directory, so you point at your `.env` explicitly:

```bash
claude mcp add ducktective -- \
  /path/to/review_ducktective/.venv/bin/ducktective-mcp \
  --env-file /path/to/review_ducktective/.env
```

Same thing via client config:

```json
{
  "mcpServers": {
    "ducktective": {
      "command": "/path/to/review_ducktective/.venv/bin/ducktective-mcp",
      "args": ["--env-file", "/path/to/review_ducktective/.env"]
    }
  }
}
```

A standalone service runs off the same executable:

```bash
uv run ducktective-mcp --transport http --port 8090
```

The settings file is set with `--env-file` or the `DUCKTECTIVE_ENV_FILE` variable;
the named file overrides the environment. The tenant is set with `--tenant` or
`MCP_TENANT_ID`: stdio has no caller identity, so the server runs as whoever started
it. Tools accept a repository by name or by ID.

## Indexing

Before review can lean on the codebase, it has to be parsed:

```bash
ducktective index .                    # current revision
ducktective index . --revision HEAD~5  # any other one
ducktective index . --skip-embeddings  # no vectors: parsing and the graph don't need them
```

From the UI, indexing kicks off in the same place you open a case: under the
repository picker you can see whether the index is built, and refresh it without
dropping to the terminal. Review will still run without an index — but one diff at
a time, with no surroundings, and the UI will say so.

A re-run only parses the files that changed — the hashes come straight from git, so
an unchanged file isn't even read. Vectors are computed by a local embedding model
(`LOCAL_EMBEDDING_MODEL`, `LOCAL_EMBEDDING_BASE_URL`); if it's unavailable, the index
still gets built and the vectors are filled in on the next run.

## Quality evaluation

The case sets with known-good answers live outside the repo — they contain code that
has no business being here. A run measures recall on the planted defects and the
false-alarm rate on diffs that are known to be clean:

```bash
ducktective eval cases.json --label baseline --repeat 3 --save

# with context from the index — this is how you measure the retrieval effect
ducktective eval cases.json --label with-context --repeat 3 \
  --repository . --tenant <id> --save
```

`--repeat` isn't about reliability: the model answers the same prompt differently
each time, and a single run measures luck. The report prints the spread next to the
average, and the "cases with context" line shows whether the index actually took
part — a "with context" run where it didn't come together is supposed to give itself
away.

## Review from the terminal

Standalone mode: no database, no Redis, no running API. All you need is a local
model — the code goes nowhere.

```bash
# what you're about to commit
ducktective review --staged --no-store

# a range of revisions
ducktective review /path/to/repo --no-store --base HEAD~1 --head HEAD

# a report for a pull request description
ducktective review --staged --no-store --format markdown
```

Output formats: `rich` (default), `json`, `markdown`.

A big commit can be narrowed down to the part you care about — `--include` takes
patterns and can be repeated. `*` spans directory separators too, so `src/report/*`
will find files at any depth:

```bash
ducktective review /path/to/repo --no-store \
  --base a1b2c3d~1 --head a1b2c3d \
  --include 'src/report/*' --include '*.py'
```

With `--fail-on`, the command returns a non-zero exit code if it finds problems at
the given level or above — which makes it usable as a git hook and in CI:

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

Stored mode (without `--no-store`) writes runs and findings to the database, needs a
`--tenant` and running infrastructure — it's there so you can label findings and
build up data for quality evaluation.

Health check: http://localhost:8000/health, API docs: http://localhost:8000/docs

## Web UI

```bash
cd apps/web
npm install
npm run dev
```

Opens at http://localhost:5173, with requests to the API proxied to port 8000 — no
CORS to configure. The tenant is set by `VITE_TENANT_ID`, the backend address by
`VITE_API_TARGET`.

The diff is shown by changed blocks; the collapsed stretches between them expand on
demand — the lines are read from the revision, not shipped along with the patch.

The "marks" section collects everything you tagged with the buttons on finding
cards: how many were confirmed, how many turned out to be a false trail, and what
share ends up confirmed. This is the raw material for evaluating the reviewer, and
without it the labeling would pile up blind.

Fonts are bundled as packages and served from the same host: the UI never reaches
out to an external CDN, same as the rest of the system.

```bash
npm run build       # build
npm run typecheck   # types
npm run codegen     # refresh API types from openapi.json
```

The API schema is regenerated from the app:

```bash
uv run python -c "import json; from ducktective.api.main import create_app; \
  print(json.dumps(create_app().openapi(), ensure_ascii=False))" > apps/web/openapi.json
```

## Migrations

```bash
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "description"
uv run alembic downgrade -1
```

Alembic reads `DATABASE_URL` from the environment — you need to export it or run the
commands through `uv run --env-file .env`.

## Development

```bash
uv run pre-commit install --install-hooks
uv run pre-commit install --hook-type commit-msg   # commit convention check
uv run pytest                 # all tests
uv run pytest -m "not integration"   # no containers, fast
uv run mypy .                 # types
uv run lint-imports           # layer boundary check
```

Formatting — strictly in this order, isort first:

```bash
uv run isort . && uv run ruff format . && uv run ruff check --fix .
```

Imports are laid out one name per line inside parentheses (`force_grid_wrap = 1`).
The `I` rule in ruff is deliberately off: ruff doesn't support this style, so isort
owns the sorting.

Commits follow [Conventional Commits](https://www.conventionalcommits.org/); the
version and CHANGELOG are generated automatically.

## Architecture

Layered DDD: `apps` → `application` → `core` (domain). Infrastructure implements the
domain's ports. Data access goes through aggregate repositories; transaction
boundaries are an explicit Unit of Work. The dependency rule is enforced by
`import-linter` in CI.

```
packages/core          domain: aggregates, value objects, events, ports
packages/application   use cases, transaction boundaries
packages/storage       SQLAlchemy, repositories, UnitOfWork, migrations
packages/indexing      tree-sitter, chunking, symbol graph, embeddings
packages/retrieval     hybrid search, reranking, diff-first retriever
packages/llm           LiteLLM, ModelRouter, cache, structured output
packages/review_graph  LangGraph nodes and graph assembly
apps/api               FastAPI: REST + WebSocket
apps/indexer           indexing worker
apps/reviewer          review worker
apps/mcp_server        MCP tools for navigating the index
```

Code-level decisions live in `docs/adr/`.
