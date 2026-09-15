# Changelog

All notable changes to this project are documented here. The format follows
[Conventional Commits](https://www.conventionalcommits.org/); versions follow
[semantic versioning](https://semver.org/).

## v0.1.0 (2026-09-15)

First public release. Everything below is new.

### Review

- End-to-end pipeline from a git diff to stored findings: unified diff parsing into
  files and hunks, a review run aggregate with a severity rubric, findings pinned to
  lines of the diff.
- Agentic reviewer: the model investigates each file with tools — the rest of the
  same change, symbol definitions, callers and references, file outlines and line
  ranges, past verdicts on the file — and answers with a structured verdict.
- Verification gates: a finding must quote code that exists at the reviewed
  revision; a claim about code the model never opened is sent back once, then
  dropped; duplicates of one defect are merged. The case reports what was discarded
  and why.
- Loop limits derived from the model's context window: tool result size, the stop
  condition and the closing output budget; a step ceiling only catches loops; a
  repeated tool call is refused.
- Review runs as a typed LangGraph graph with a Postgres checkpointer: stop, resume
  from the checkpoint, restart; per-file degradation marks; files left unreviewed are
  reported instead of looking clean.
- A run queues an incremental index build for its own revision and waits for it.
- Findings and the investigation trail are written in the language of the run.

### Index and retrieval

- Code index in PostgreSQL: tree-sitter parsing for Python, JavaScript and
  TypeScript, block chunking for markup and text, a symbol graph with resolved call,
  inheritance and import edges, `tsvector` and pgvector on every chunk.
- Hybrid search with reciprocal rank fusion; prose questions are translated into
  candidate identifiers before the search.
- Diff-first retrieval for the single-pass reviewer.
- Incremental builds by git content hash, visible stages, cancellation, and vectors
  computed as a separate pass that survives an unavailable embedding model.
- Embeddings from a quantised `nomic-embed-text` in the Ollama that ships in compose,
  or from any OpenAI-compatible server chosen per build; servers with the same
  weights share one vector set. Generated and vendored paths get no vectors.
- Navigation works without an index too — git at the reviewed revision, with the
  source of every answer stated.

### Chat and MCP

- Chat with the codebase over a WebSocket: the same tools as the reviewer, streamed
  tokens, a folded tool trail, attached documents searchable by a dedicated tool,
  fallback to the next allowed model when one refuses.
- MCP server exposing the index to Claude Code, Cursor and other clients:
  repositories, semantic search, definitions, callers, file context.

### Models and privacy

- LiteLLM as the single gateway; a ModelRouter that picks a model per node from
  its requirements and the repository's egress policy.
- Three trust levels — local, private remote, training remote — and a per-repository
  policy that caps them.
- Provider connections owned by the organization: one key, the provider's whole
  catalogue, encrypted at rest; presets that say what you pay with.
- Fallbacks, cooldowns and exponential back-off; a Redis response cache keyed by
  prompt version.

### Organizations and sign-in

- Keycloak OpenID Connect sign-in, organizations, invitations, owner and member
  roles; PostgreSQL row-level security on every organization-scoped table.
- CLI sign-in through the OAuth device flow.

### Interface

- React application: cases with the diff and findings on their lines, severity and
  verdict filters, confirm / false lead / defer on every finding, a live investigation
  trail, a marks page with the share of confirmed findings.
- Indexes page with build state, the two layers of the index and the choice of the
  embedding server; models page with connections and presets; organization page.
- English and Russian interface with a switch in the top bar; an installation log
  viewer for administrators.

### CLI

- `ducktective review` — standalone review without a database or a queue, output as
  rich, JSON or Markdown, `--fail-on` for git hooks and CI, `--include` to narrow a
  change.
- `ducktective index`, `ducktective eval`, `ducktective dev` to run the whole stack
  with merged logs.

### Platform

- Layered DDD with aggregates, ports, an explicit Unit of Work and import-linter
  contracts; strict typing; tests on testcontainers.
- Two arq workers with separate queues; jobs defer while an index builds; a run that
  outlives the job time limit is marked failed with the reason.
- Schema check on startup with migrations under a lock; structured JSON logging with a
  JSONL file sink; Docker Compose with Postgres, Redis, Keycloak and Ollama.
