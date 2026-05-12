"""FastAPI + Inngest background job server for repomind.

Three Inngest functions:
  repomind/ingest_repo     — fetch + chunk (step 1) then embed + store (step 2)
  repomind/run_agent       — full agent loop in one step; result cached for polling
  repomind/agent_completed — post-run metrics hook fired by the sync Streamlit path

Three REST helpers:
  POST /api/ingest             — trigger a repo ingest job
  POST /api/query              — trigger an async agent run, returns session_id
  GET  /api/result/{session_id} — poll for the agent result

Run with:
    uvicorn server:app --reload --port 8000

Then start the Inngest Dev Server in another terminal:
    npx inngest-cli@latest dev -u http://localhost:8000/api/inngest

Inngest Dev UI is available at http://localhost:8288
"""
from __future__ import annotations

import asyncio
import logging

import inngest
import inngest.fast_api
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from eval.metrics import _estimate_cost_usd
from ingest import embed_and_store_chunks, fetch_and_chunk_repo
from inngest_setup import inngest_client

logger = logging.getLogger("uvicorn")

# In-memory cache for async agent results — keyed by full session_id UUID.
_RESULT_CACHE: dict[str, dict] = {}


# ─── Inngest function 1: ingest repo ────────────────────────────────────────

@inngest_client.create_function(
    fn_id="repomind-ingest-repo",
    trigger=inngest.TriggerEvent(event="repomind/ingest_repo"),
)
async def ingest_repo_fn(ctx: inngest.Context) -> dict:
    """Fetch a GitHub repo, chunk files, embed with Ollama, store in ChromaDB."""
    repo_slug: str = ctx.event.data["repo"]
    mode: str = ctx.event.data.get("mode", "ast")
    event_id: str = ctx.event.id

    chunks_data = await ctx.step.run(
        "fetch-and-chunk",
        lambda: fetch_and_chunk_repo(repo_slug, mode, event_id=event_id),
    )
    result = await ctx.step.run(
        "embed-and-store",
        lambda: embed_and_store_chunks(chunks_data),
    )
    logger.info(
        "repomind/ingest_repo done: %d chunks → collection '%s'",
        result["total_chunks"],
        result["collection_name"],
    )
    return result


# ─── Inngest function 2: async agent run ────────────────────────────────────

@inngest_client.create_function(
    fn_id="repomind-run-agent",
    trigger=inngest.TriggerEvent(event="repomind/run_agent"),
)
async def run_agent_fn(ctx: inngest.Context) -> dict:
    """ReAct loop driven step-by-step so each tool call is a visible Inngest checkpoint."""
    import time
    import uuid
    from agent import _generate, _parse_action, query_rewrite
    from prompts import REACT_PROMPT_TEMPLATE
    from tools import _TOOL_METRICS, run_tool

    query: str = ctx.event.data["query"]
    collection_name: str = ctx.event.data["collection_name"]
    session_id = str(uuid.uuid4())
    run_start = time.time()

    # Step 1 — rewrite the query for semantic search
    rewritten: str = await ctx.step.run(
        "query-rewrite",
        lambda: query_rewrite(query),
    )

    scratchpad = ""

    for step_num in range(1, 7):
        prompt = REACT_PROMPT_TEMPLATE.format(
            question=query,
            rewritten=rewritten,
            scratchpad=scratchpad,
        )

        # LLM generate — step so timing is visible in Inngest and result is memoized on retry
        raw: str = await ctx.step.run(
            f"llm-generate-{step_num}",
            lambda p=prompt: _generate(p, max_new_tokens=1000, temperature=0.2),
        )

        if "Final Answer:" in raw:
            answer = raw.split("Final Answer:", 1)[-1].strip()
            result = {
                "session_id": session_id,
                "answer": answer,
                "steps": step_num,
                "total_latency_s": round(time.time() - run_start, 2),
            }
            _RESULT_CACHE[session_id] = result
            logger.info("repomind/run_agent done: session=%s steps=%d", session_id, step_num)
            return result

        parsed = _parse_action(raw)
        if parsed is None:
            result = {
                "session_id": session_id,
                "answer": raw,
                "steps": step_num,
                "total_latency_s": round(time.time() - run_start, 2),
            }
            _RESULT_CACHE[session_id] = result
            return result

        tool_name, args = parsed

        # Each tool call is its own step — vector_search gets a descriptive label
        if tool_name == "vector_search":
            step_label = f"vector-search-{step_num}"
        else:
            step_label = f"{tool_name}-{step_num}"

        def _run_tool(tn=tool_name, a=args) -> dict:
            _TOOL_METRICS.set({})
            res = run_tool(tn, a, collection_name)
            m = _TOOL_METRICS.get({})
            return {
                "result": res,
                "embed_ms": m.get("embed_ms"),
                "chroma_ms": m.get("chroma_ms"),
            }

        step_out: dict = await ctx.step.run(step_label, _run_tool)
        scratchpad += raw + f"\nObservation: {step_out['result']}\n\n"

    result = {
        "session_id": session_id,
        "answer": "Could not find a complete answer after max steps.",
        "steps": 6,
        "total_latency_s": round(time.time() - run_start, 2),
    }
    _RESULT_CACHE[session_id] = result
    return result


# ─── Inngest function 3: Streamlit path step checkpoints ────────────────────

@inngest_client.create_function(
    fn_id="repomind-streamlit-step",
    trigger=inngest.TriggerEvent(event="repomind/streamlit_step"),
)
async def streamlit_step_fn(ctx: inngest.Context) -> dict:
    """Receives per-stage events fired by the synchronous Streamlit agent path.

    Each stage (query_rewrite, llm_generate, tool_call, final_answer, *_error)
    fires a separate repomind/streamlit_step event from agent.py. This function
    runs a single log-step so every stage appears as a separate timed run in
    the Inngest Dev UI — giving the same per-step visibility as the async path.
    """
    data = ctx.event.data

    def _log(d: dict) -> dict:
        step = d.get("step", "unknown")
        session = d.get("session_id", "?")[:8]
        latency = d.get("latency_ms") or d.get("total_latency_ms")
        if "error" in step:
            logger.warning(
                "streamlit step ERROR: session=%s step=%s error=%s",
                session, step, d.get("error", "?"),
            )
        else:
            logger.info(
                "streamlit step: session=%s step=%s latency_ms=%s",
                session, step, latency,
            )
        return d

    return await ctx.step.run("log-step", lambda: _log(data))


# ─── Inngest function 4: post-run metrics hook ──────────────────────────────

@inngest_client.create_function(
    fn_id="repomind-agent-completed",
    trigger=inngest.TriggerEvent(event="repomind/agent_completed"),
)
async def agent_completed_fn(ctx: inngest.Context) -> dict:
    """Post-processing for every completed agent run (fired by the sync Streamlit path)."""
    data = ctx.event.data

    def _compute(d: dict) -> dict:
        input_tok = d.get("input_tokens", 0)
        output_tok = d.get("output_tokens", 0)
        cost_usd = _estimate_cost_usd(input_tok, output_tok)
        return {
            "session_id": d.get("session_id"),
            "query": (d.get("query") or "")[:120],
            "steps": d.get("steps", 0),
            "stop_reason": d.get("stop_reason", "end_turn"),
            "input_tokens": input_tok,
            "output_tokens": output_tok,
            "cost_usd": round(cost_usd, 6),
            "total_latency_s": d.get("total_latency_s"),
            "embed_ms": d.get("embed_ms"),
            "chroma_ms": d.get("chroma_ms"),
        }

    metrics = await ctx.step.run("compute-metrics", lambda: _compute(data))
    logger.info(
        "repomind/agent_completed: session=%s steps=%d $%.6f",
        metrics["session_id"],
        metrics["steps"],
        metrics["cost_usd"],
    )
    return metrics


# ─── FastAPI app ─────────────────────────────────────────────────────────────

app = FastAPI(title="repomind server")  # 4 Inngest functions registered below
inngest.fast_api.serve(app, inngest_client, [ingest_repo_fn, run_agent_fn, streamlit_step_fn, agent_completed_fn])


class IngestRequest(BaseModel):
    repo: str
    mode: str = "ast"


class QueryRequest(BaseModel):
    query: str
    collection_name: str


@app.post("/api/ingest")
async def trigger_ingest(req: IngestRequest):
    """Trigger a background repo ingestion job."""
    if req.repo.count("/") != 1:
        raise HTTPException(status_code=400, detail="repo must be in 'owner/name' form")
    await inngest_client.send(
        inngest.Event(
            name="repomind/ingest_repo",
            data={"repo": req.repo, "mode": req.mode},
        )
    )
    return {"status": "triggered", "repo": req.repo, "mode": req.mode}


@app.post("/api/query")
async def trigger_query(req: QueryRequest):
    """Trigger an async agent run. Poll /api/result/{session_id} for the answer."""
    event = await inngest_client.send(
        inngest.Event(
            name="repomind/run_agent",
            data={"query": req.query, "collection_name": req.collection_name},
        )
    )
    return {"status": "triggered", "event_id": getattr(event, "id", None)}


@app.get("/api/result/{session_id}")
async def get_result(session_id: str):
    """Return cached agent result if ready, else 404."""
    result = _RESULT_CACHE.get(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="result not ready yet")
    return result


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
