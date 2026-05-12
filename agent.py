"""Core agent orchestrator — text-based ReAct loop using rag-learning's generate endpoint.

Uses httpx to POST to QWEN_GENERATE_URL (rag-learning's QwenService) and drives a
Thought → Action → Observation loop until the model outputs "Final Answer:" or
max_steps is hit.

    LLM ──▶ parse Action ──▶ run_tool ──▶ Observation ──▶ LLM ...
                              ──▶ Final Answer ──▶ return

Inngest visibility (Streamlit path):
  Every meaningful stage fires a repomind/streamlit_step event so the
  Inngest Dev UI shows per-step latency for the synchronous Streamlit
  flow — same visibility as the async ctx.step.run path in server.py.

  Checkpoints fired:
    query_rewrite       — LLM rewrite latency + result
    query_rewrite_error — if the rewrite LLM call fails
    llm_generate        — per-iteration LLM latency + parsed action
    llm_generate_error  — if the generate call throws
    tool_call           — per-tool latency, embed_ms, chroma_ms, result size
    tool_call_error     — if run_tool raises
    final_answer        — total latency, steps, stop reason
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from typing import Any

import httpx
from dotenv import load_dotenv

from logger import log_step
from prompts import QUERY_REWRITE_PROMPT, REACT_PROMPT_TEMPLATE
from tools import _TOOL_METRICS, run_tool

load_dotenv()

QWEN_GENERATE_URL = os.getenv("QWEN_GENERATE_URL", "")
VLLM_API_KEY = os.getenv("VLLM_API_KEY", "")


def _generate(prompt: str, max_new_tokens: int = 512, temperature: float = 0.2) -> str:
    resp = httpx.post(
        QWEN_GENERATE_URL,
        json={"prompt": prompt, "max_new_tokens": max_new_tokens, "temperature": temperature},
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {VLLM_API_KEY}",
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


def _send_event(name: str, data: dict) -> None:
    """Fire-and-forget event to Inngest Dev Server (daemon thread, never blocks)."""
    def _send() -> None:
        try:
            url = os.getenv("INNGEST_DEV_EVENT_URL", "http://localhost:8288/e/repomind-dev")
            httpx.post(url, json=[{"name": name, "data": data}], timeout=2.0)
        except Exception:
            pass
    threading.Thread(target=_send, daemon=True).start()


def _fire_monitoring_event(data: dict) -> None:
    _send_event("repomind/agent_completed", data)


def _fire_step_event(session_id: str, step: str, data: dict) -> None:
    """Fire a repomind/streamlit_step event for Streamlit path checkpoint visibility."""
    _send_event("repomind/streamlit_step", {"session_id": session_id, "step": step, **data})


def query_rewrite(user_query: str) -> str:
    """Rewrite a user question into a compact semantic-search query."""
    return _generate(
        QUERY_REWRITE_PROMPT.format(query=user_query),
        max_new_tokens=100,
        temperature=0.1,
    )


def _parse_action(text: str) -> tuple[str, dict] | None:
    """Extract (tool_name, args_dict) from a ReAct response, or None if not found."""
    action_match = re.search(r"Action:\s*(\w+)", text)
    if not action_match:
        return None
    tool_name = action_match.group(1).strip()

    input_match = re.search(r"Action Input:\s*(\{.*?\})", text, re.DOTALL)
    if input_match:
        try:
            args = json.loads(input_match.group(1))
        except json.JSONDecodeError:
            args = {}
    else:
        args = {}

    return tool_name, args


def run_agent(
    user_query: str,
    collection_name: str,
    max_steps: int = 6,
) -> dict[str, Any]:
    """Drive the ReAct loop until Final Answer or max_steps."""
    session_id = str(uuid.uuid4())
    run_start = time.time()

    # ── Checkpoint: query_rewrite ────────────────────────────────────────────
    t0 = time.time()
    try:
        rewritten = query_rewrite(user_query)
    except Exception as e:
        _fire_step_event(session_id, "query_rewrite_error", {
            "error": str(e),
            "query": user_query[:200],
        })
        raise

    _fire_step_event(session_id, "query_rewrite", {
        "latency_ms": round((time.time() - t0) * 1000),
        "original_query": user_query[:200],
        "rewritten": rewritten[:200],
    })
    log_step(session_id, 0, "query_rewrite", {
        "original": user_query,
        "rewritten": rewritten,
    })

    scratchpad = ""
    total_embed_ms: int = 0
    total_chroma_ms: int = 0

    for step in range(1, max_steps + 1):
        prompt = REACT_PROMPT_TEMPLATE.format(
            question=user_query,
            rewritten=rewritten,
            scratchpad=scratchpad,
        )

        # ── Checkpoint: llm_generate ─────────────────────────────────────────
        t0 = time.time()
        try:
            raw = _generate(prompt, max_new_tokens=1000, temperature=0.2)
        except Exception as e:
            llm_latency_ms = round((time.time() - t0) * 1000)
            _fire_step_event(session_id, "llm_generate_error", {
                "step_num": step,
                "latency_ms": llm_latency_ms,
                "error": str(e),
            })
            log_step(session_id, step, "llm_error", {"error": str(e)})
            raise

        llm_latency = round(time.time() - t0, 2)
        llm_latency_ms = round(llm_latency * 1000)

        # Final answer check
        if "Final Answer:" in raw:
            answer = raw.split("Final Answer:", 1)[-1].strip()
            total_latency = round(time.time() - run_start, 2)

            _fire_step_event(session_id, "llm_generate", {
                "step_num": step,
                "latency_ms": llm_latency_ms,
                "action": "final_answer",
            })
            log_step(session_id, step, "final_answer", {
                "answer": answer,
                "llm_latency_s": llm_latency,
                "total_latency_s": total_latency,
                "total_steps": step,
            })
            _fire_step_event(session_id, "final_answer", {
                "total_latency_ms": round(total_latency * 1000),
                "total_steps": step,
                "stop_reason": "stop",
                "embed_ms": total_embed_ms or None,
                "chroma_ms": total_chroma_ms or None,
            })
            _fire_monitoring_event({
                "session_id": session_id,
                "query": user_query[:200],
                "steps": step,
                "stop_reason": "stop",
                "total_latency_s": total_latency,
                "embed_ms": total_embed_ms or None,
                "chroma_ms": total_chroma_ms or None,
            })
            return {
                "session_id": session_id,
                "answer": answer,
                "steps": step,
                "messages": [{"role": "assistant", "content": scratchpad + raw}],
            }

        # Parse tool call
        parsed = _parse_action(raw)
        if parsed is None:
            total_latency = round(time.time() - run_start, 2)
            _fire_step_event(session_id, "llm_generate", {
                "step_num": step,
                "latency_ms": llm_latency_ms,
                "action": "no_action",
            })
            log_step(session_id, step, "unexpected_stop", {"llm_latency_s": llm_latency})
            _fire_step_event(session_id, "final_answer", {
                "total_latency_ms": round(total_latency * 1000),
                "total_steps": step,
                "stop_reason": "no_action",
                "embed_ms": total_embed_ms or None,
                "chroma_ms": total_chroma_ms or None,
            })
            _fire_monitoring_event({
                "session_id": session_id,
                "query": user_query[:200],
                "steps": step,
                "stop_reason": "no_action",
                "total_latency_s": total_latency,
                "embed_ms": total_embed_ms or None,
                "chroma_ms": total_chroma_ms or None,
            })
            return {
                "session_id": session_id,
                "answer": raw,
                "steps": step,
                "messages": [{"role": "assistant", "content": scratchpad + raw}],
            }

        tool_name, args = parsed
        _fire_step_event(session_id, "llm_generate", {
            "step_num": step,
            "latency_ms": llm_latency_ms,
            "action": tool_name,
        })
        log_step(session_id, step, "tool_call", {
            "tool": tool_name,
            "args": args,
            "llm_latency_s": llm_latency,
        })

        # ── Checkpoint: tool_call ────────────────────────────────────────────
        _TOOL_METRICS.set({})
        t1 = time.time()
        try:
            tool_result = run_tool(tool_name, args, collection_name)
        except Exception as e:
            tool_latency_ms = round((time.time() - t1) * 1000)
            _fire_step_event(session_id, "tool_call_error", {
                "step_num": step,
                "tool": tool_name,
                "latency_ms": tool_latency_ms,
                "error": str(e),
            })
            log_step(session_id, step, "tool_error", {"tool": tool_name, "error": str(e)})
            raise

        tool_latency = round(time.time() - t1, 2)
        tool_metrics = _TOOL_METRICS.get({})
        embed_ms = tool_metrics.get("embed_ms") or 0
        chroma_ms = tool_metrics.get("chroma_ms") or 0
        total_embed_ms += embed_ms
        total_chroma_ms += chroma_ms

        result_str = str(tool_result)
        _fire_step_event(session_id, "tool_call", {
            "step_num": step,
            "tool": tool_name,
            "latency_ms": round(tool_latency * 1000),
            "embed_ms": embed_ms or None,
            "chroma_ms": chroma_ms or None,
            "result_chars": len(result_str),
        })
        log_step(session_id, step, "tool_result", {
            "tool": tool_name,
            "result_preview": result_str[:200],
            "result_chars": len(result_str),
            "tool_latency_s": tool_latency,
            **tool_metrics,
        })

        scratchpad += raw + f"\nObservation: {result_str}\n\n"

    # ── Checkpoint: max_steps_reached ────────────────────────────────────────
    total_latency = round(time.time() - run_start, 2)
    log_step(session_id, max_steps, "max_steps_reached", {})
    _fire_step_event(session_id, "final_answer", {
        "total_latency_ms": round(total_latency * 1000),
        "total_steps": max_steps,
        "stop_reason": "max_steps_reached",
        "embed_ms": total_embed_ms or None,
        "chroma_ms": total_chroma_ms or None,
    })
    _fire_monitoring_event({
        "session_id": session_id,
        "query": user_query[:200],
        "steps": max_steps,
        "stop_reason": "max_steps_reached",
        "embed_ms": total_embed_ms or None,
        "chroma_ms": total_chroma_ms or None,
        "total_latency_s": total_latency,
    })
    return {
        "session_id": session_id,
        "answer": "I couldn't find a complete answer after max steps.",
        "steps": max_steps,
        "messages": [{"role": "assistant", "content": scratchpad}],
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python agent.py <collection_name> <query...>", file=sys.stderr)
        sys.exit(2)
    collection = sys.argv[1]
    query = " ".join(sys.argv[2:])
    result = run_agent(query, collection)
    print("\n" + "=" * 60)
    print("FINAL ANSWER:")
    print(result["answer"])
    print(f"\nSteps: {result['steps']}")
