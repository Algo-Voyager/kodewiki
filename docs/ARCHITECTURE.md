# Architecture

End-to-end working of repomind — a grounded code-Q&A agent over a GitHub repository.

## What it does

Given a GitHub repo and a natural-language question, repomind finds the relevant code via a local semantic index, then asks an LLM to answer while *only* citing what it retrieved. Retrieval is mediated by tool calls inside a ReAct loop — the model decides what to fetch, when to search again, and when it has enough to answer.

## High-level diagram

```
  ┌────────────────────────────────────────────────────────────────────┐
  │                     Next.js Frontend (port 3000)                   │
  │                                                                    │
  │  Sidebar                   /chat                  /benchmarks      │
  │  • ingest trigger     • framer-motion msgs    • benchmark_results  │
  │  • indexed repos      • per-col queue         • AST vs naive chart │
  │  • drag-resize        • contextRef history                         │
  └────┬───────────────────────┬──────────────────────────────────────┘
       │ POST /api/ingest      │ POST /api/query  (+ history[])
       │                       │ GET  /api/result/{event_id}  (poll)
       ▼                       ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │                    server.py  (FastAPI, port 8000)               │
  │                  + Inngest webhook at /api/inngest               │
  │                                                                  │
  │  repomind/ingest_repo          repomind/run_agent                │
  │    step: fetch-and-chunk         step: compress-history          │
  │    step: embed-and-store         step: query-rewrite             │
  │                                  step: llm-generate-N            │
  │  repomind/agent_completed        step: vector-search-N / tool-N  │
  │    step: compute-metrics         step: check-anomalies           │
  └────────────────────────┬─────────────────────────────────────────┘
                           │ blocking I/O via asyncio.to_thread
                           ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │                         agent.py                                 │
  │  query_rewrite(query, history_context) → compact search query    │
  │  ReAct loop (text-based, up to max_steps=6):                     │
  │    httpx.post(QWEN_GENERATE_URL) → parse Action / Action Input   │
  │    run_tool(name, args, collection) → Observation                │
  │    ... repeat until "Final Answer:" appears                      │
  │  returns {answer, compressed_history, steps, usage}              │
  └────────────────┬─────────────────────────────────────────────────┘
                   │                      │
        embed via openai SDK         raw file via PyGithub
        (EMBED_BASE_URL/Modal)            │
                   ▼                      ▼
  ┌─────────────────────┐    ┌────────────────────────┐
  │   ChromaDB          │    │   GitHub API           │
  │   ./chroma_db/      │    │   (GITHUB_TOKEN)       │
  │   <owner>_<repo>    │    └────────────────────────┘
  │   _ast | _naive     │
  └─────────────────────┘

  Side channels:
    logger.py  → agent_logs.jsonl → eval/metrics.py → /logs page
    tools.py   → _TOOL_METRICS (ContextVar) → embed_ms / chroma_ms in logs
    eval/compare.py → LLM-as-judge (Claude) → benchmark_results.json → /benchmarks
    Inngest Dev UI (localhost:8288) ← all job/event step traces
```

## Components

| Module | Role |
|---|---|
| `inngest_setup.py` | Shared Inngest client singleton (`app_id="repomind"`, dev mode). Imported by `server.py` and `agent.py`. |
| `server.py` | FastAPI app with Inngest webhook at `/api/inngest`. Three Inngest functions: `ingest_repo`, `run_agent`, `agent_completed`. REST: `POST /api/ingest`, `POST /api/query`, `GET /api/result/{id}`. All step handlers are `async def` with `asyncio.to_thread` for blocking I/O. |
| `ingest.py` | Fetch a repo via PyGithub, chunk (AST for `.py`, H2 sections for `.md`, sliding-window otherwise), embed via Modal `BAAI/bge-small-en-v1.5`, upsert into ChromaDB. Exposes `fetch_and_chunk_repo` and `embed_and_store_chunks` for Inngest; `main()` for CLI. |
| `agent.py` | Text-based ReAct orchestrator. `httpx.post(QWEN_GENERATE_URL)` → parse `Action:` / `Action Input:` → `run_tool` → `Observation:` → repeat. Accepts `history_block` for conversation context. Fires `repomind/agent_completed` event after every run (daemon thread). |
| `tools.py` | `vector_search` (Modal embed → Chroma), `get_file` (PyGithub raw), `get_recent_commits`. `TOOL_SCHEMAS` used for prompt descriptions only (not API function-calling). Tracks `embed_ms`/`chroma_ms` via `_TOOL_METRICS` ContextVar. |
| `prompts.py` | `REACT_PROMPT_TEMPLATE` (`{question}`, `{rewritten}`, `{scratchpad}`, `{history_block}`), `QUERY_REWRITE_PROMPT` (`{query}`, `{history_context}`), `COMPRESS_HISTORY_PROMPT` for lazy history compression. |
| `logger.py` | Appends one JSON line per event to `agent_logs.jsonl`. Readers: `get_recent_logs`, `get_session_logs`. |
| `frontend/app/layout.tsx` | Root layout: `Sidebar` + Plus Jakarta Sans font via `next/font/google`. |
| `frontend/app/chat/page.tsx` | Animated chat UI. Per-collection queue (`inFlightRef` + `queuesRef`): same collection queues, different collections run in parallel. `contextRef` holds compressed history per collection. Framer-motion message animations, glass-morphism input card, mouse-follow gradient. |
| `frontend/components/Sidebar.tsx` | Resizable sidebar (160–400 px via drag handle). Lucide icon nav (Chat/Logs/Benchmarks). Ingest form with AST/naive mode toggle. Indexed repos list with selection. |
| `frontend/components/ui/animated-ai-chat.tsx` | `AnimatedTextarea` (auto-resize, violet focus ring), `TypingDots` (staggered 3-dot animation), `useAutoResizeTextarea` hook. |
| `frontend/lib/api.ts` | `triggerQuery(query, collection, history[])`, `pollResult(eventId)`, `fetchCollections()`, `ingestRepo(repo, mode)`. Defines `ContextMessage` and `AgentResult` types. |
| `eval/compare.py` | AST vs naive benchmark. Modal embeddings for retrieval, Claude (`claude-opus-4-7`) as judge, scores chunks 1–5. Writes `frontend/public/benchmark_results.json`. |
| `eval/metrics.py` | Reads `agent_logs.jsonl`, computes per-session + aggregate latency/token/cost stats. |
| `eval/test_queries.py` | Correctness harness — 5 fixed queries, must-contain/must-not-contain keyword scoring. |

## Workflow 1 — Ingestion

### Via frontend sidebar (recommended — Inngest-monitored)

1. User enters `owner/repo`, selects `AST` or `Naive`, clicks "Ingest Repo".
2. Frontend POSTs to `POST /api/ingest` → `server.py` sends `repomind/ingest_repo` event.
3. Inngest runs two steps (visible at localhost:8288):

**Step 1 — `fetch-and-chunk`** (`ingest.fetch_and_chunk_repo`):
- Load `GITHUB_TOKEN`, resolve repo via PyGithub.
- Walk the tree, skip `node_modules` / `.git` / `dist` / `build` and files over 500 KB.
- For each allowed file (`.py`, `.md`, `.ts`, `.tsx`, `.js`, `.jsx`, `.txt`):
  - `.py` + `ast` mode → parse with `ast.walk`, one chunk per function/class.
  - `.md` → split at `## ` H2 headings.
  - Anything else → naive fixed-size window (2000 chars, 50 overlap).
- Write chunks to `./chroma_db/.chunks_<collection>_<event_id>.jsonl`. The `event_id` makes the file idempotent across Inngest retries.

**Step 2 — `embed-and-store`** (`ingest.embed_and_store_chunks`):
- Read the temp JSONL chunk-by-chunk.
- Embed each chunk via `openai.OpenAI(base_url=EMBED_BASE_URL)` — Modal `BAAI/bge-small-en-v1.5`.
- Upsert into Chroma collection `<owner>_<repo>_<mode>` with metadata: `type`, `name`, `file_path`, `line_start`, `line_end`, `language`, `heading`.
- Delete the temp file in a `finally` block.

**Result:** persistent Chroma collection at `./chroma_db`. Frontend returns immediately; watch progress in Inngest Dev UI.

### Via CLI

```bash
python ingest.py <owner>/<repo> <ast|naive>
```

Calls both functions sequentially. Same logic, no Inngest visibility.

## Workflow 2 — Query

1. **Submit.** Frontend posts `{query, collection_name, history: ContextMessage[]}` to `POST /api/query`. Server enqueues `repomind/run_agent` Inngest event and returns `{event_id}`. Frontend polls `GET /api/result/{event_id}` every second.

2. **Compress history (Inngest step).** If total history chars > 12 K, summarize messages older than the last 4 pairs using Claude (`COMPRESS_HISTORY_PROMPT`). Always returns `effective_history` regardless of compression.

3. **Query rewrite (Inngest step).** `agent.query_rewrite(user_query, history_context)` → compact semantic search query.

4. **ReAct loop steps.** Each `llm-generate-N` and `vector-search-N` is a separate Inngest step visible in Dev UI.

5. **Return.** Result dict includes `{answer, compressed_history, steps, usage}`. Frontend stores `compressed_history` in `contextRef[collection]` for the next turn.

## Workflow 3 — Evaluation

- **Correctness** (`eval/test_queries.py`) — 5 predefined questions, keyword pass/fail. Writes `eval_results.jsonl`.
- **AST vs naive** (`eval/compare.py`) — top-3 chunks from both collections for 8 benchmark queries, Claude as judge (1–5 score). Writes `frontend/public/benchmark_results.json`. Run: `python eval/compare.py <owner>/<repo>`.
- **Aggregate metrics** (`eval/metrics.py`) — reads `agent_logs.jsonl`, avg/median/p95 latency, total tokens, estimated cost.

## Data stores

| File / directory | Written by | Read by | Gitignored |
|---|---|---|---|
| `./chroma_db/` | `ingest.embed_and_store_chunks` | `tools.vector_search`, `eval/compare.py` | ✅ |
| `./chroma_db/.chunks_*.jsonl` | `ingest.fetch_and_chunk_repo` | `ingest.embed_and_store_chunks` | ✅ (temp, auto-deleted) |
| `agent_logs.jsonl` | `logger.log_step` | `eval/metrics.py`, `/logs` page | ✅ |
| `eval_results.jsonl` | `eval/test_queries.py` | `/benchmarks` page | ✅ |
| `frontend/public/benchmark_results.json` | `eval/compare.py` | `/benchmarks` page | ✅ |
| `.env` | user | all modules | ✅ |

## Design choices

- **Text-based ReAct, not OpenAI function calling.** The Qwen endpoint is a raw text completion API — it doesn't support `tools=` in the request. The agent parses `Action:` / `Action Input:` from the model output manually.

- **Tool-call-mediated retrieval.** The model decides when to search, when to read a file, and when it has enough to answer — not a fixed "embed → retrieve → answer" pipeline.

- **Embeddings are Modal, not local.** All embedding calls go through `EMBED_BASE_URL` (rag-learning's Modal deployment). There is no Ollama dependency anywhere.

- **Inngest for ingest + agent.** Both ingestion and agent runs go through Inngest for durable execution, retry, and step-level visibility in the Dev UI. All Inngest step handlers are `async def` with `asyncio.to_thread` wrapping blocking I/O.

- **`_TOOL_METRICS` ContextVar for sub-tool latency.** `embed_ms` and `chroma_ms` are tracked in `tools.py` using a `contextvars.ContextVar` — thread-safe and async-safe across concurrent sessions.

- **Collections versioned by chunking mode.** `<owner>_<repo>_ast` and `<owner>_<repo>_naive` coexist in ChromaDB — this is what makes the AST vs naive benchmark possible without re-ingesting.

- **Stateless backend, stateful frontend history.** Conversation context is managed in `contextRef` in `chat/page.tsx`. The backend receives history per-request, optionally compresses it, and returns `compressed_history`. No server-side session state.

- **Per-collection frontend queue.** `inFlightRef` + `queuesRef` in the chat page ensure that queries against the same collection run sequentially (later queries queue), while queries against different collections run in parallel.

---

## Challenges & lessons learned

Ordered by depth of insight — the harder the root cause, the higher it appears.

### 1. Inngest sync handlers block the asyncio event loop

**Problem:** After migrating the agent to Inngest steps, the frontend's polling (`GET /api/result/{id}`) would return 500 errors even though the Inngest Dev UI showed the function completing successfully. The result cache was being written, but the poll endpoint wasn't reading it.

**Root cause:** The Inngest Python SDK's `step_async.py` calls step handler callables via `maybe_await(handler(*args))` — directly on the event loop, with no thread pool. A sync handler that blocks (e.g., `httpx.post`, `chromadb.query`) holds the event loop thread for the duration of that call, starving uvicorn's request handler. By the time the step finished and the result was cached, FastAPI was already returning a timeout to the frontend.

**Fix:** All Inngest step handlers converted to `async def`. Every blocking call wrapped with `asyncio.to_thread(blocking_fn, ...)`. This keeps the event loop free during I/O so uvicorn can serve the poll endpoint concurrently.

**Lesson:** With async frameworks, any sync I/O in an async context is a silent performance killer. Inngest's SDK doesn't warn you — it just blocks. Always wrap.

---

### 2. Conversation history requires a stateless compression contract

**Problem:** The agent is stateless per-request. To support multi-turn chat, the full conversation history must be passed with every query — but at 16 K+ chars, this pushes the model's context limit and inflates latency/cost.

**Root cause:** Naive approaches either truncate (losing early context) or pass everything (ballooning the prompt). The challenge is deciding *what to keep* without losing the thread of the conversation.

**Fix:** Lazy compression triggered at 75% of the char limit (12 K out of 16 K). When triggered: keep the last 4 message pairs verbatim (for immediate context coherence), summarize everything older with a single Claude call (`COMPRESS_HISTORY_PROMPT`). The backend returns `compressed_history` in every response; the frontend stores it in `contextRef[collection]` and sends it back next turn. Compression only fires when needed — most short conversations never trigger it.

**Lesson:** "Keep recent + lazy summarize" is the right shape for this problem. The threshold and verbatim tail length are the tuning knobs; 12 K / 4 pairs worked well in practice.

---

### 3. Per-collection message queuing with parallel cross-collection support

**Problem:** A user might send a second question before the first one finishes. Simply firing both requests in parallel against the same collection produces incoherent context — the second query doesn't have the first answer yet when it compresses history.

**Root cause:** The chat page was sending every query immediately via `triggerQuery`, regardless of in-flight state.

**Fix:** `inFlightRef` (Set of active collection names) + `queuesRef` (Map of collection → pending query queue) in the chat page. When a query arrives for a collection that's already in-flight, it's appended to that collection's queue and executed only after the previous one settles. Queries against *different* collections are always independent and run in parallel. Queue drain is handled inside `executeQuery`'s `finally` block.

**Lesson:** useRef (not useState) for the queue — React re-renders must not reset in-flight tracking mid-execution. Closures over stale state are the enemy here.

---

### 4. AST vs naive benchmark used the wrong embedding backend

**Problem:** `eval/compare.py` was using `ollama.embeddings()` — from an early prototype phase — while the rest of the project had long since migrated to Modal embeddings. Running the benchmark would silently produce meaningless retrieval results (different embedding space from what ChromaDB was indexed with).

**Root cause:** The eval script was never updated when the embedding backend changed.

**Fix:** Replaced `ollama.embeddings()` with `openai.OpenAI(base_url=EMBED_BASE_URL).embeddings.create(model=EMBED_MODEL, input=query)` — identical to the pattern in `tools.py`. Also moved the output path from `./benchmark_results.json` (project root, not served) to `frontend/public/benchmark_results.json` (served as a static asset to the Next.js `/benchmarks` page).

**Lesson:** Eval scripts drift from production code. Any script that shares infrastructure (embedding models, vector DBs) with the main system needs to be updated as a first-class concern when that infrastructure changes.

---

### 5. Sidebar resize required document-level event listeners, not element-level

**Problem:** Implementing a drag-to-resize sidebar using `onMouseMove` on the drag handle element itself: the cursor frequently escapes the thin (4 px) handle during fast drags, breaking the drag mid-gesture.

**Root cause:** `onMouseMove` on a small element only fires when the cursor is over that element. Fast mouse movement outpaces the element boundaries.

**Fix:** `onMouseDown` on the drag handle sets `isDragging = true` and captures start position in refs. A `useEffect` on `isDragging` attaches `mousemove` and `mouseup` to `document` — these fire regardless of where the cursor is. On `mouseup`, `isDragging` is cleared and the listeners are removed. Width is clamped to [160, 400] px.

**Lesson:** Drag gestures must be captured at the document level after `mousedown`. Element-level `mousemove` is only appropriate for hover effects.

---

### 6. Sidebar overflow required precise flex tree structure

**Problem:** The sidebar's "Indexed Repos" list wasn't scrollable — once more repos were added, the list overflowed outside the sidebar viewport with no scroll affordance.

**Root cause:** `overflow-y-auto` on a flex child has no effect unless the child has a bounded height. By default, flex children stretch to fill the flex axis — but without `min-h-0`, a flex child will refuse to shrink below its content's natural height. The browser treats content height as the minimum, so `overflow` never activates.

**Fix:** The sidebar `<aside>` gets `h-full overflow-hidden`. The collections section gets `flex-1 min-h-0 overflow-y-auto`. `flex-1` lets it grow; `min-h-0` overrides the browser's implicit minimum; `overflow-y-auto` then has a bounded container to activate against.

**Lesson:** `overflow-y: auto` on a flex child requires `min-height: 0` (or `min-h-0` in Tailwind). This is one of the most common "why isn't my scroll working" bugs in flex layouts.

---

### 7. Lucide React does not export a Figma icon

**Problem:** The `AnimatedAIChat` component referenced `Figma` from `lucide-react`, which does not exist in the package — causing a TypeScript compile error and breaking the entire `/chat` page.

**Root cause:** The component was written for a version of Lucide or a different icon library that included a Figma brand icon. Brand icons are generally not included in Lucide due to trademark restrictions.

**Fix:** Replaced `Figma` with `LayoutTemplate` — semantically close enough for a "design/layout" action in the command palette, and available in lucide-react.

**Lesson:** Brand icons (Figma, Slack, GitHub, etc.) are rarely in general-purpose icon sets. Always verify icon names exist before using them, or use the library's icon search.

---

### 8. AnimatedTextarea name collided with shadcn's Textarea

**Problem:** Importing both the custom `Textarea` from `animated-ai-chat.tsx` and shadcn's `Textarea` from `components/ui/textarea.tsx` in the same file caused a TypeScript name collision and conflicting prop types.

**Root cause:** Both components were exported under the name `Textarea`.

**Fix:** Renamed the animated component to `AnimatedTextarea` throughout its file and all import sites. The shadcn `Textarea` retains its original name for backward compatibility with other pages.

**Lesson:** Custom component wrappers should always have distinct names from the primitives they wrap — "Animated", "Fancy", or semantic prefixes prevent silent shadowing in barrel imports.
