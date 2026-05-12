# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project state

All core modules are implemented: `ingest.py`, `tools.py`, `prompts.py`, `logger.py`, `agent.py`, `app.py`, `eval/*.py`. Inngest-based monitoring is active via `server.py` and `inngest_setup.py`. When adding features, conform to the module responsibilities below.

## Commands

```bash
# One-time setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in VLLM_API_KEY, QWEN_GENERATE_URL, EMBED_BASE_URL, GITHUB_TOKEN

# Deploy Modal services from rag-learning (LLM + embeddings)
cd ../rag-learning && modal deploy qwen_modal.py && cd ../repomind

# Terminal 1 — FastAPI + Inngest backend
uvicorn server:app --port 8000

# Terminal 2 — Inngest Dev Server (UI at http://localhost:8288)
npx inngest-cli@latest dev -u http://localhost:8000/api/inngest

# Terminal 3 — Streamlit UI
streamlit run app.py

# ── Standalone CLI (no server required) ──────────────────────────────────
python ingest.py <owner/repo> <ast|naive>
python tools.py <owner>_<repo>_<mode>
python agent.py <owner>_<repo>_<mode> "your question here"
```

No test runner, linter, or formatter is configured yet. If you add one, update this section.

## Architecture

The system is a from-scratch RAG agent — **no LangChain, no LlamaIndex**. Keep that constraint when adding features; do not introduce those frameworks.

**Data flow:**

1. `ingest.py` pulls a GitHub repo via PyGithub, chunks every file (AST-based for Python, heading-based for Markdown, sliding window for everything else), calls the Modal embedding API (`EMBED_BASE_URL/embeddings`) via the `openai` SDK, and persists vectors to ChromaDB at `./chroma_db`.

2. At query time, `app.py` (Streamlit) calls `run_agent(user_query, collection_name)` directly (synchronous path). The agent in `agent.py` runs a text-based **ReAct loop**: it POSTs to `QWEN_GENERATE_URL` (`httpx`), parses the model's `Action:` / `Action Input:` output, runs the tool, appends `Observation:` to the prompt, and repeats until `Final Answer:` appears.

3. Every tool call goes through `tools.py`. `vector_search` embeds the query via the Modal embedding API and queries ChromaDB. Latency for each (`embed_ms`, `chroma_ms`) is tracked in a `_TOOL_METRICS` ContextVar and reported in both `log_step` and `_fire_monitoring_event`.

4. After every run, `agent.py` fires a `repomind/agent_completed` event to the Inngest Dev Server (daemon thread, non-blocking). The `agent_completed_fn` in `server.py` runs `compute-metrics` as a step.

5. The async Inngest path (`repomind/run_agent`) in `server.py` drives the same ReAct loop step-by-step using `ctx.step.run`, making each LLM call (`llm-generate-N`) and each tool call (`vector-search-N`, `get-file-N`) a separate visible checkpoint in the Inngest Dev UI.

## Module responsibilities

- `ingest.py` — repo fetch + chunk + embed + write to Chroma. Exposes `fetch_and_chunk_repo` and `embed_and_store_chunks` for Inngest steps. Runs standalone as CLI. Uses `openai` SDK with `EMBED_BASE_URL` for embeddings — no Ollama.
- `agent.py` — text-based ReAct loop via `httpx.post(QWEN_GENERATE_URL)`. Exposes `run_agent(user_query, collection_name)` and internal helpers `_generate`, `_parse_action`, `query_rewrite` (used by `server.py`). Fires `repomind/agent_completed` event after every run.
- `tools.py` — tool implementations (`vector_search`, `get_file`, `get_recent_commits`). `TOOL_SCHEMAS` is in OpenAI function format but only used for the prompt description — not passed to the LLM via API. Tracks embed + Chroma latency via `_TOOL_METRICS` ContextVar.
- `prompts.py` — `REACT_PROMPT_TEMPLATE` (full ReAct prompt with tool descriptions, format with `.format(question=, rewritten=, scratchpad=)`) and `QUERY_REWRITE_PROMPT` (format with `.format(query=...)`).
- `logger.py` — structured JSONL logging to `agent_logs.jsonl` (gitignored).
- `inngest_setup.py` — shared Inngest client singleton (imported by `server.py` and `agent.py`).
- `server.py` — FastAPI + Inngest server. Three Inngest functions: `repomind/ingest_repo` (2 steps: fetch-and-chunk, embed-and-store), `repomind/run_agent` (per-step loop: query-rewrite → llm-generate-N → vector-search-N → …), `repomind/agent_completed` (compute-metrics). REST: `POST /api/ingest`, `POST /api/query`, `GET /api/result/{session_id}`.
- `app.py` — Streamlit front end. Ingestion triggers `POST /api/ingest`. Chat calls `run_agent` synchronously for immediate UX.
- `deploy/qwen_modal.py` — Modal deployment with two services: `serve` (Qwen2.5-7B via vLLM, GPU A10G, OpenAI-compatible) and `embedding_api` (BAAI/bge-small-en-v1.5 via sentence-transformers, CPU, OpenAI-compatible). Currently **not used** — repomind points at rag-learning's `qwen-7b-service` deployment instead.
- `eval/` — offline evaluation: `test_queries.py` (correctness), `metrics.py` (aggregate stats), `compare.py` (AST vs naive).

## Model and dependencies

- **LLM**: `Qwen/Qwen2.5-7B-Instruct` via rag-learning's `QwenService` on Modal. Endpoint: `QWEN_GENERATE_URL`. Request format: `{"prompt": str, "max_new_tokens": int, "temperature": float}`. Response: `{"response": str}`. Called via `httpx.post`. **Not OpenAI-compatible** — no function calling support, which is why the agent uses a text-based ReAct loop.
- **Embeddings**: `BAAI/bge-small-en-v1.5` via rag-learning's `embedding_api` on Modal. Endpoint: `EMBED_BASE_URL` (must include `/v1` suffix). OpenAI-compatible `/v1/embeddings`. Called via `openai.OpenAI(base_url=EMBED_BASE_URL)`. Produces 384-dim vectors.
- **Vector store**: ChromaDB persistent client at `./chroma_db` (gitignored). Treat as disposable — rebuild with `python ingest.py`. Switching embedding models changes vector dimensions and requires full re-ingest.

## Key env vars

| Variable | Used by | Notes |
|----------|---------|-------|
| `VLLM_API_KEY` | agent.py, tools.py, ingest.py | Shared key for both Modal services |
| `QWEN_GENERATE_URL` | agent.py | rag-learning LLM endpoint |
| `EMBED_BASE_URL` | tools.py, ingest.py | Must end with `/v1` |
| `EMBED_MODEL` | tools.py, ingest.py | `BAAI/bge-small-en-v1.5` |
| `GITHUB_TOKEN` | ingest.py, tools.py | Repo read access |

## Secrets and generated files

`.env`, `chroma_db/`, `agent_logs.jsonl`, `eval_results.jsonl`, and `benchmark_results.json` are gitignored. Never commit them.
