"""Core agent orchestrator — ReAct-style tool-use loop with OpenAI-compatible LLM.

Uses the OpenAI SDK with a configurable base_url so any vLLM-served model
(Qwen, Llama, Mistral, …) works without code changes — matching rag-learning's
pattern of pointing the OpenAI client at VLLM_BASE_URL.

One agent, one loop. Given a user question and a Chroma collection name,
rewrites the query for semantic search, then iterates:

    LLM ──▶ tool_calls? ──▶ run_tool ──▶ tool result ──▶ LLM ...

...until finish_reason == "stop" or ``max_steps`` is hit. Every LLM call,
tool call, and tool result is logged to ``agent_logs.jsonl`` via log_step.
A fire-and-forget event is sent to Inngest Dev Server after every run for
dashboard visibility (repomind/agent_completed).
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
import uuid
from typing import Any

import httpx
from dotenv import load_dotenv
from openai import OpenAI

from logger import log_step
from prompts import QUERY_REWRITE_PROMPT, SYSTEM_PROMPT
from tools import TOOL_SCHEMAS, _TOOL_METRICS, run_tool

load_dotenv()

MODEL = os.getenv("VLLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")
_client: OpenAI | None = None


def _get_client() -> OpenAI:
    """Lazy client init — matches rag-learning's data_loader.py pattern."""
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.getenv("VLLM_API_KEY", "no-key"),
            base_url=os.getenv("VLLM_BASE_URL"),  # None → default OpenAI endpoint
        )
    return _client


def _fire_monitoring_event(data: dict) -> None:
    """Send repomind/agent_completed to Inngest Dev Server in a daemon thread.

    Daemon thread ensures it never stalls the Streamlit response.
    Swallows all errors so monitoring never breaks the agent.
    """
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
    response = _get_client().chat.completions.create(
        model=MODEL,
        max_tokens=200,
        messages=[{
            "role": "user",
            "content": QUERY_REWRITE_PROMPT.format(query=user_query),
        }],
    )
    return (response.choices[0].message.content or "").strip()


def run_agent(
    user_query: str,
    collection_name: str,
    max_steps: int = 6,
) -> dict[str, Any]:
    """Drive the agent loop until the model finishes or ``max_steps`` is hit."""
    client = _get_client()
    session_id = str(uuid.uuid4())
    run_start = time.time()

    rewritten = query_rewrite(user_query)
    log_step(session_id, 0, "query_rewrite", {
        "original": user_query,
        "rewritten": rewritten,
    })

    # System prompt as first message (OpenAI convention)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Original question: {user_query}\n"
                f"Optimized search query: {rewritten}"
            ),
        },
    ]

    for step in range(1, max_steps + 1):
        t0 = time.time()
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=2000,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )
        llm_latency = round(time.time() - t0, 2)

        choice = response.choices[0]
        message = choice.message
        finish_reason = choice.finish_reason
        input_tok = response.usage.prompt_tokens if response.usage else 0
        output_tok = response.usage.completion_tokens if response.usage else 0

        if finish_reason == "stop":
            answer = message.content or ""
            total_latency = round(time.time() - run_start, 2)
            log_step(session_id, step, "final_answer", {
                "answer": answer,
                "llm_latency_s": llm_latency,
                "total_latency_s": total_latency,
                "total_steps": step,
                "input_tokens": input_tok,
                "output_tokens": output_tok,
            })
            result = {
                "session_id": session_id,
                "answer": answer,
                "steps": step,
                "messages": messages,
                "usage": {"input_tokens": input_tok, "output_tokens": output_tok},
            }
            _fire_monitoring_event({
                "session_id": session_id,
                "query": user_query[:200],
                "steps": step,
                "stop_reason": "stop",
                "input_tokens": input_tok,
                "output_tokens": output_tok,
                "total_latency_s": total_latency,
            })
            return result

        if finish_reason != "tool_calls" or not message.tool_calls:
            # length, content_filter, or stop without tool calls
            answer = message.content or ""
            total_latency = round(time.time() - run_start, 2)
            log_step(session_id, step, "unexpected_stop", {
                "stop_reason": finish_reason,
                "llm_latency_s": llm_latency,
            })
            _fire_monitoring_event({
                "session_id": session_id,
                "query": user_query[:200],
                "steps": step,
                "stop_reason": finish_reason,
                "total_latency_s": total_latency,
            })
            return {
                "session_id": session_id,
                "answer": answer or f"[stopped: {finish_reason}]",
                "steps": step,
                "messages": messages,
            }

        # Append assistant message preserving full tool_calls structure
        messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ],
        })

        for tc in message.tool_calls:
            tool_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                args = {}

            log_step(session_id, step, "tool_call", {
                "tool": tool_name,
                "args": args,
                "llm_latency_s": llm_latency,
            })

            _TOOL_METRICS.set({})
            t1 = time.time()
            result = run_tool(tool_name, args, collection_name)
            tool_latency = round(time.time() - t1, 2)
            tool_metrics = _TOOL_METRICS.get({})

            result_str = str(result)
            log_step(session_id, step, "tool_result", {
                "tool": tool_name,
                "result_preview": result_str[:200],
                "result_chars": len(result_str),
                "tool_latency_s": tool_latency,
                **tool_metrics,
            })

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_str,
            })

    total_latency = round(time.time() - run_start, 2)
    log_step(session_id, max_steps, "max_steps_reached", {})
    _fire_monitoring_event({
        "session_id": session_id,
        "query": user_query[:200],
        "steps": max_steps,
        "stop_reason": "max_steps_reached",
        "total_latency_s": total_latency,
    })
    return {
        "session_id": session_id,
        "answer": "I couldn't find a complete answer after max steps.",
        "steps": max_steps,
        "messages": messages,
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
    if "usage" in result:
        print(
            f"Tokens: {result['usage']['input_tokens']} in / "
            f"{result['usage']['output_tokens']} out"
        )
