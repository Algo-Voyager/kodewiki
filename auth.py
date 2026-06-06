"""Per-request override for the GitHub PAT.

When a request hits /api/ingest or /api/query with an `X-Github-Token` header,
the Inngest function handler stores that token in a ContextVar at the start of
the run. GitHub-using code (`tools.py`, `ingest.py`) then reads via
`get_github_token()` — the override wins, with the env-var as fallback.

This keeps the codebase ContextVar-clean (no `os.environ` monkey-patching, no
thread-safety hazards) and lets a dashboard user paste their own PAT if the
deployed env-var token has expired or rate-limited.
"""
from __future__ import annotations

import contextvars
import os

_github_token_override: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "github_token_override", default=None
)

# Same override pattern for the LLM / embeddings auth key (Modal Bearer).
# Settings UI lets a user paste their own VLLM_API_KEY in case the deploy's
# default is wrong / rotated / they're pointing at their own Modal app.
_vllm_api_key_override: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "vllm_api_key_override", default=None
)


def set_github_token_override(token: str | None) -> None:
    """Set the per-context PAT override. Pass None or "" to clear."""
    _github_token_override.set(token.strip() if token and token.strip() else None)


def get_github_token() -> str:
    """Return the effective GitHub PAT — override first, env second.

    Raises RuntimeError if neither is configured. Callers can choose to surface
    that as a 4xx with a hint that the user should paste a token in Settings.
    """
    token = _github_token_override.get()
    if token:
        return token
    token = os.getenv("GITHUB_TOKEN", "")
    if not token:
        raise RuntimeError(
            "No GitHub token available. Set GITHUB_TOKEN in env, or paste one "
            "into the dashboard's Settings page (sent as X-Github-Token header)."
        )
    return token


def set_vllm_api_key_override(key: str | None) -> None:
    """Per-context LLM/embeddings key override. Pass None or "" to clear."""
    _vllm_api_key_override.set(key.strip() if key and key.strip() else None)


def get_vllm_api_key() -> str:
    """Return the effective Modal / vLLM Bearer key — override first, env second.

    Returns "" if neither is set (downstream HTTP calls then fail with 401 from
    Modal; callers can choose to validate up-front if they want a nicer error).
    """
    key = _vllm_api_key_override.get()
    if key:
        return key
    return os.getenv("VLLM_API_KEY", "")
