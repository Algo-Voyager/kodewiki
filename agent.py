"""Core agent orchestrator — text-based ReAct loop using rag-learning's generate endpoint.

Uses httpx to POST to QWEN_GENERATE_URL (rag-learning's QwenService) and drives a
Thought → Action → Observation loop until the model outputs "Final Answer:" or
max_steps is hit.

    LLM ──▶ parse Action ──▶ run_tool ──▶ Observation ──▶ LLM ...
                              ──▶ Final Answer ──▶ return
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


def _fire_monitoring_event(data: dict) -> None:
    def _send() -> None:
        try:
            url = os.getenv("INNGEST_DEV_EVENT_URL", "http://localhost:8288/e/repomind-dev")
            httpx.post(
                url,
                json=[{"name": "repomind/agent_completed", "data": data}],
                timeout=2.0,
            )
        except Exception:
            pass

    threading.Thread(target=_send, daemon=True).start()


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

    rewritten = query_rewrite(user_query)
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

        t0 = time.time()
        raw = _generate(prompt, max_new_tokens=1000, temperature=0.2)
        llm_latency = round(time.time() - t0, 2)

        # Final answer check
        if "Final Answer:" in raw:
            answer = raw.split("Final Answer:", 1)[-1].strip()
            total_latency = round(time.time() - run_start, 2)
            log_step(session_id, step, "final_answer", {
                "answer": answer,
                "llm_latency_s": llm_latency,
                "total_latency_s": total_latency,
                "total_steps": step,
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
            # Model gave a plain response without Action or Final Answer
            total_latency = round(time.time() - run_start, 2)
            log_step(session_id, step, "unexpected_stop", {"llm_latency_s": llm_latency})
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
        log_step(session_id, step, "tool_call", {
            "tool": tool_name,
            "args": args,
            "llm_latency_s": llm_latency,
        })

        _TOOL_METRICS.set({})
        t1 = time.time()
        tool_result = run_tool(tool_name, args, collection_name)
        tool_latency = round(time.time() - t1, 2)
        tool_metrics = _TOOL_METRICS.get({})
        total_embed_ms += tool_metrics.get("embed_ms", 0) or 0
        total_chroma_ms += tool_metrics.get("chroma_ms", 0) or 0

        result_str = str(tool_result)
        log_step(session_id, step, "tool_result", {
            "tool": tool_name,
            "result_preview": result_str[:200],
            "result_chars": len(result_str),
            "tool_latency_s": tool_latency,
            **tool_metrics,
        })

        # Extend scratchpad with this step
        scratchpad += raw + f"\nObservation: {result_str}\n\n"

    total_latency = round(time.time() - run_start, 2)
    log_step(session_id, max_steps, "max_steps_reached", {})
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
