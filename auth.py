"""Per-request overrides for credentials + tenancy.

Three ContextVars carry per-request state set by REST handlers (and forwarded
into Inngest function handlers via event data):

  GitHub PAT       — X-Github-Token header  → get_github_token()
  LLM Bearer key   — X-VLLM-Key header      → get_vllm_api_key()
  Tenant ID        — X-Tenant-Id header     → get_tenant_id()

Tenants isolate anonymous users — a UUID minted in the browser scopes every
ChromaDB collection, every agent log entry, every metric. With no header, the
tenant falls back to ``SHARED_TENANT`` (used by CLI ingests + local smoke
tests, never reachable from the browser because browsers always send a UUID).
"""
from __future__ import annotations

import contextvars
import os
import re

_github_token_override: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "github_token_override", default=None
)

# Same override pattern for the LLM / embeddings auth key (Modal Bearer).
# Settings UI lets a user paste their own VLLM_API_KEY in case the deploy's
# default is wrong / rotated / they're pointing at their own Modal app.
_vllm_api_key_override: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "vllm_api_key_override", default=None
)

# Per-request tenant ID (UUID). Set from X-Tenant-Id header. Falls back to
# SHARED_TENANT when missing so CLI ingests + dev have a consistent home.
_tenant_id_override: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "tenant_id_override", default=None
)

SHARED_TENANT = "shared"
# Double-underscore separator between tenant + repo slug. UUIDs only contain
# hex + single hyphens, so "__" cannot appear inside a tenant ID and the split
# is unambiguous.
TENANT_SEP = "__"
# Whitelist tenant IDs to a safe character class. Block anything path-y or
# containing the separator to keep qualify/strip reversible.
_TENANT_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


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


# ─── LLM provider switching ─────────────────────────────────────────────────
# Text generation can be routed through one of four providers per request.
# Embeddings always use the Modal endpoint (see ingest.py / tools.py).
#
# Provider is selected by the X-LLM-Provider header (Settings → dropdown).
# When unset, falls back to "vllm" (the deploy's bundled Modal Qwen endpoint).

SUPPORTED_PROVIDERS = ("vllm", "anthropic", "openai", "gemini")

# Sensible default model per provider — cheap + fast tiers. Override via the
# X-LLM-Model header (Settings → model text input).
DEFAULT_MODELS = {
    "anthropic": "claude-haiku-4-5-20251001",
    "openai":    "gpt-4o-mini",
    "gemini":    "gemini-2.5-flash",
}

_llm_provider_override: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "llm_provider_override", default=None
)
_llm_api_key_override: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "llm_api_key_override", default=None
)
_llm_model_override: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "llm_model_override", default=None
)


def set_llm_provider_override(provider: str | None) -> None:
    """Set the active text-generation provider. Unknown values clear the override."""
    if not provider:
        _llm_provider_override.set(None)
        return
    p = provider.strip().lower()
    _llm_provider_override.set(p if p in SUPPORTED_PROVIDERS else None)


def get_llm_provider() -> str:
    """Return the active text-generation provider — override first, ``vllm`` otherwise."""
    return _llm_provider_override.get() or "vllm"


def set_llm_api_key_override(key: str | None) -> None:
    """Set the API key for the active non-vllm provider (Anthropic / OpenAI / Gemini)."""
    _llm_api_key_override.set(key.strip() if key and key.strip() else None)


def get_llm_api_key() -> str:
    """Provider-specific key for Anthropic / OpenAI / Gemini.

    Returns "" if unset — caller should raise a helpful error pointing the user
    to Settings before making the HTTP call.
    """
    return _llm_api_key_override.get() or ""


def set_llm_model_override(model: str | None) -> None:
    """Set the model name for the active provider. Pass None / "" to fall back to default."""
    _llm_model_override.set(model.strip() if model and model.strip() else None)


def get_llm_model(provider: str | None = None) -> str:
    """Return the effective model name — override first, provider default otherwise."""
    model = _llm_model_override.get()
    if model:
        return model
    return DEFAULT_MODELS.get(provider or get_llm_provider(), "")


# ─── Tenancy ────────────────────────────────────────────────────────────────

def set_tenant_id_override(tenant_id: str | None) -> None:
    """Set the per-context tenant. Pass None or "" to clear (falls back to SHARED_TENANT)."""
    if tenant_id is None:
        _tenant_id_override.set(None)
        return
    tid = tenant_id.strip()
    if not tid or not _TENANT_RE.match(tid) or TENANT_SEP in tid:
        _tenant_id_override.set(None)
        return
    _tenant_id_override.set(tid)


def get_tenant_id() -> str:
    """Return the effective tenant ID — override first, ``SHARED_TENANT`` otherwise.

    Always returns a non-empty string safe to embed in a collection name.
    """
    tid = _tenant_id_override.get()
    return tid or SHARED_TENANT


def qualify_collection(name: str, tenant_id: str | None = None) -> str:
    """Prefix a bare collection name with the tenant scope.

    >>> qualify_collection("0xnktd_fireranger_ast", "abc-123")
    'abc-123__0xnktd_fireranger_ast'

    Idempotent: if ``name`` already starts with the tenant prefix it's returned
    unchanged. Pass ``tenant_id=None`` to read it from the ContextVar.
    """
    tid = tenant_id or get_tenant_id()
    prefix = f"{tid}{TENANT_SEP}"
    if name.startswith(prefix):
        return name
    return prefix + name


def strip_tenant(name: str) -> tuple[str, str]:
    """Split a qualified collection name into (tenant_id, bare_name).

    If ``name`` lacks the ``tenant__`` prefix, returns ("", name) — used by the
    list endpoint to filter out pre-existing legacy collections.
    """
    if TENANT_SEP not in name:
        return "", name
    tid, _, bare = name.partition(TENANT_SEP)
    return tid, bare


def belongs_to(name: str, tenant_id: str | None = None) -> bool:
    """True if a qualified collection name belongs to the given tenant."""
    tid = tenant_id or get_tenant_id()
    return name.startswith(f"{tid}{TENANT_SEP}")
