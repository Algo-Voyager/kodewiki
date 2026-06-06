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
