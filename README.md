# repomind

A developer documentation agent — point it at a GitHub repo and ask questions about the code in plain English. Answers are grounded in the repo: the agent retrieves relevant chunks from a local vector index and cites file paths and line numbers.

> Full architecture, chunking deep-dive, and engineering decisions → [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

---

## Stack

| Layer | Technology |
|-------|-----------|
| **LLM** | `Qwen/Qwen2.5-7B-Instruct` on Modal (custom `/generate` endpoint) |
| **Agent loop** | Text-based ReAct — parses `Action` / `Action Input` from model output |
| **Embeddings** | `BAAI/bge-small-en-v1.5` on Modal — OpenAI-compatible `/v1/embeddings` |
| **Vector DB** | ChromaDB (persistent, `./chroma_db`) |
| **Backend** | FastAPI + [Inngest](https://www.inngest.com) for durable background jobs |
| **Frontend** | Next.js (App Router) |
| **GitHub API** | PyGithub |
| **Production deploy** | Vercel (frontend) + Render (backend) + Inngest Cloud + Modal |

No LangChain. No LlamaIndex.

> AST-based chunking is validated by the [cAST (2025)](https://arxiv.org/abs/2506.15655) paper — *Enhancing Code RAG with Structural Chunking via Abstract Syntax Tree* — which reports +4.3 Recall@5 and +5.6 Pass@1 on Python repos over naive sliding-window chunking.

---

## Setup

### 1. Python environment

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Deploy Modal services

Both the LLM and embeddings run on Modal (shared with rag-learning). Deploy once:

```bash
cd ../rag-learning
modal deploy qwen_modal.py
cd ../repomind
```

### 3. Environment variables

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `VLLM_API_KEY` | Shared API key for both Modal services |
| `QWEN_GENERATE_URL` | LLM generate endpoint URL from Modal |
| `EMBED_BASE_URL` | Embedding endpoint URL from Modal — **must end with `/v1`** |
| `EMBED_MODEL` | `BAAI/bge-small-en-v1.5` |
| `GITHUB_TOKEN` | GitHub personal access token (repo read access) |

### 4. Run

Open three terminals:

```bash
# Terminal 1 — FastAPI + Inngest backend
uvicorn server:app --port 8000

# Terminal 2 — Inngest Dev Server  (UI at http://localhost:8288)
npx inngest-cli@latest dev -u http://localhost:8000/api/inngest

# Terminal 3 — Next.js frontend  (http://localhost:3000)
cd frontend && npm install && npm run dev
```

---

## Usage

**Ingest a repo** — enter `owner/repo` in the sidebar, choose AST or Naive mode, click "Ingest Repo". Progress is visible in the Inngest Dev UI at `localhost:8288`.

**Ask questions** — select an indexed repo from the sidebar and type your question in the chat.

The agent processes the query asynchronously — the UI shows a live "Agent working…" indicator while the ReAct loop runs tool calls in the background.

![Agent processing a query in real time](assest/waiting_for_response.png)

Once the loop completes, the answer streams in with file-path citations. Asking for a diagram or flowchart produces an interactive Mermaid chart you can click to zoom.

![LLM response with codebase explanation](assest/llm_response.png)

Every run is tracked as a durable job in Inngest — open `localhost:8288` to inspect each pipeline step and its timing.

![Inngest Dev Server showing a full agent run with step-level timing](assest/inngest_info.png)

**Run the benchmark** — after ingesting both `ast` and `naive` collections:

```bash
python eval/compare.py <owner>/<repo>
```

Results appear on the `/benchmarks` page.

### Settings — bring your own API keys

Open `/settings` to paste personal credentials when the server's defaults are expired, rate-limited, or you want to query a private repo your team owns:

| Key | Header | Used for |
|-----|--------|----------|
| GitHub PAT | `X-Github-Token` | Repo ingestion, file/commit fetch |
| LLM API key | `X-VLLM-Key` | Qwen generation + embeddings |

Both are stored in `localStorage` under `repomind:user-tokens:v1` (browser-local, never sent anywhere except as headers on `/api/ingest` and `/api/query`). The backend's `auth.py` reads each header into a `ContextVar` override; when absent, it falls back to the server-side env var. Clear from the same page when done on a shared device.

### Chat persistence

Chat threads and the per-collection compressed history are persisted to `localStorage` under `repomind:chat-state:v1`, so refreshing the page restores the conversation in place.

### Inspect ingested chunks (prod)

`GET /api/collections/{name}/chunks` returns the raw chunks ChromaDB has for a collection — useful for verifying ingestion without shelling into the box.

```bash
BASE=https://<your-render-app>.onrender.com/api

curl "$BASE/collections" | jq                                       # list collections
curl "$BASE/collections/<name>/chunks?limit=5" | jq                 # first 5 chunks
curl "$BASE/collections/<name>/chunks?file_path=server.py" | jq     # filter by file
curl "$BASE/collections/<name>/chunks?chunk_type=function" | jq     # filter by type
curl "$BASE/collections/<name>/chunks?limit=50&offset=50" | jq      # paginate
```

Params: `limit` (≤500), `offset`, `file_path`, `chunk_type` (`function|class|doc|code`). Returns `{chunks, total, limit, offset}`.

### CLI (no server required)

```bash
python ingest.py <owner>/<repo> <ast|naive>
python agent.py <owner>_<repo>_<mode> "How does error handling work?"
python tools.py <owner>_<repo>_<mode>   # smoke-test retrieval
```

---

## Project layout

```
repomind/
├── server.py              # FastAPI + Inngest (ingest, run_agent, agent_completed, chunks)
├── inngest_setup.py       # Shared Inngest client (prod/dev via INNGEST_DEV)
├── auth.py                # Per-request ContextVar overrides for PAT + LLM key
├── ingest.py              # Repo fetch → chunk → embed → ChromaDB
├── agent.py               # ReAct loop via httpx → QWEN_GENERATE_URL
├── tools.py               # vector_search, get_file, get_recent_commits
├── prompts.py             # ReAct, query-rewrite, history-compression prompts
├── logger.py              # Structured JSONL logging → agent_logs.jsonl
├── render.yaml            # Render web-service spec (free tier)
├── DEPLOY.md              # Step-by-step Vercel + Render + Inngest Cloud guide
├── assest/                # Screenshots used in this README
├── frontend/              # Next.js UI
│   ├── app/chat/          # Chat page (with localStorage persistence)
│   ├── app/logs/          # Logs page
│   ├── app/benchmarks/    # Benchmark results page
│   ├── app/settings/      # BYO API keys page (GitHub PAT + LLM key)
│   ├── components/        # Sidebar, MarkdownRenderer (Mermaid), AnimatedTextarea
│   └── lib/api.ts         # API client + authHeaders() injecting X-Github-Token / X-VLLM-Key
├── eval/
│   ├── compare.py         # AST vs naive benchmark (Qwen as judge)
│   ├── test_queries.py    # Correctness test suite
│   └── metrics.py         # Latency / token / cost metrics
├── docs/
│   └── ARCHITECTURE.md    # System design, chunking, pipeline, challenges
├── requirements.txt
├── .env.example
└── .gitignore
```

---

## Production deployment

End-to-end deploy guide: [`DEPLOY.md`](DEPLOY.md). Summary:

| Component | Host | Notes |
|-----------|------|-------|
| Frontend | Vercel | Set `NEXT_PUBLIC_API_URL=https://<render-app>.onrender.com/api` |
| Backend | Render | `render.yaml` provided. Free tier → `chroma_db/` is ephemeral (wiped on redeploy) and the dyno sleeps after 15 min idle |
| Background jobs | Inngest Cloud | Set `INNGEST_EVENT_KEY` + `INNGEST_SIGNING_KEY`; backend auto-syncs functions on first `PUT /api/inngest` |
| LLM + embeddings | Modal | Reuse the rag-learning deployment |

Extra env vars for prod:

| Variable | Notes |
|----------|-------|
| `INNGEST_EVENT_KEY`, `INNGEST_SIGNING_KEY` | Inngest Cloud credentials |
| `INNGEST_DEV` | `1` for local dev server, omit/`0` in prod |
| `CHROMA_DB_PATH` | Override `./chroma_db` if mounting persistent disk |
| `NEXT_PUBLIC_API_URL` | Frontend → backend base URL (Vercel build-time) |

CORS middleware on `server.py` allows the Vercel origin to call the Render backend directly.

---

## Secrets and generated files

`.env`, `chroma_db/`, `agent_logs.jsonl`, `eval_results.jsonl`, and `frontend/public/benchmark_results.json` are gitignored. Never commit them.
