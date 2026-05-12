"""Deploy two services under the "repomind-vllm" Modal app:

  1. serve         — Qwen2.5-7B-Instruct LLM via vLLM  (GPU: A10G)
                     OpenAI-compatible /v1/chat/completions
  2. embedding_api — BAAI/bge-small-en-v1.5 embeddings (CPU)
                     OpenAI-compatible /v1/embeddings

─── One-time setup ───────────────────────────────────────────────────────────
    # 1. Install Modal and authenticate
    .venv/bin/pip install modal
    .venv/bin/modal token new

    # 2. Hugging Face token (required for gated models; fine to leave empty for Qwen)
    .venv/bin/modal secret create huggingface-secret HF_TOKEN=hf_xxx

    # 3. API key to protect both endpoints
    .venv/bin/modal secret create vllm-api-key VLLM_API_KEY=choose-a-long-random-string

─── Deploy ───────────────────────────────────────────────────────────────────
    # Ephemeral — streams logs, stops on Ctrl-C
    .venv/bin/modal serve deploy/qwen_modal.py

    # Persistent — stays up, scales to zero when idle
    .venv/bin/modal deploy deploy/qwen_modal.py

    Modal prints two public URLs, e.g.:
      LLM        : https://<workspace>--repomind-vllm-serve.modal.run
      Embeddings : https://<workspace>--repomind-vllm-embedding-api.modal.run

    Set in .env:
      VLLM_BASE_URL=https://<workspace>--repomind-vllm-serve.modal.run/v1
      EMBED_BASE_URL=https://<workspace>--repomind-vllm-embedding-api.modal.run
      VLLM_API_KEY=<your key>
      VLLM_MODEL=Qwen/Qwen2.5-7B-Instruct
      EMBED_MODEL=BAAI/bge-small-en-v1.5

─── Test LLM ─────────────────────────────────────────────────────────────────
    BASE=https://<workspace>--repomind-vllm-serve.modal.run
    KEY=$VLLM_API_KEY

    curl $BASE/v1/chat/completions \
        -H "Authorization: Bearer $KEY" \
        -H "Content-Type: application/json" \
        -d '{"model": "Qwen/Qwen2.5-7B-Instruct",
             "messages": [{"role": "user", "content": "What is a ReAct agent?"}]}'

─── Test embeddings ──────────────────────────────────────────────────────────
    EMBED=https://<workspace>--repomind-vllm-embedding-api.modal.run
    KEY=$VLLM_API_KEY

    curl $EMBED/v1/embeddings \
        -H "Authorization: Bearer $KEY" \
        -H "Content-Type: application/json" \
        -d '{"input": ["Hello world"], "model": "BAAI/bge-small-en-v1.5"}'

─── Stop ─────────────────────────────────────────────────────────────────────
    .venv/bin/modal app stop repomind-vllm

    Or run the cleanup script to also delete cached volumes:
    bash cleanup_modal.sh
"""

import modal

try:
    from fastapi import FastAPI, HTTPException, Request
except ImportError:
    FastAPI = object
    Request = object
    HTTPException = Exception

# ── LLM config ────────────────────────────────────────────────────────────────
MODEL_NAME     = "Qwen/Qwen2.5-7B-Instruct"
MODEL_REVISION = "main"
MAX_MODEL_LEN  = 8192
VLLM_VERSION   = "0.6.4.post1"

GPU_TYPE = "A10G"
N_GPU    = 1

# ── Embedding model config ────────────────────────────────────────────────────
EMBED_MODEL_ID  = "BAAI/bge-small-en-v1.5"
EMBED_MODEL_DIR = "/embed-cache"

MINUTES = 60

# ── Container images ──────────────────────────────────────────────────────────
vllm_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        f"vllm=={VLLM_VERSION}",
        "huggingface_hub[hf_transfer]",
    )
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

embed_image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "sentence-transformers>=3.0.0",
        "torch>=2.2.0",
        "fastapi[standard]",
    )
)

# ── Volumes — weights cached so restarts are fast ─────────────────────────────
hf_cache    = modal.Volume.from_name("huggingface-cache", create_if_missing=True)
vllm_cache  = modal.Volume.from_name("vllm-cache",        create_if_missing=True)
embed_cache = modal.Volume.from_name("embed-cache",        create_if_missing=True)

# ── Modal app ─────────────────────────────────────────────────────────────────
app = modal.App("repomind-vllm")


# ── 1. LLM service (vLLM, OpenAI-compatible /v1/chat/completions) ─────────────
@app.function(
    image=vllm_image,
    gpu=GPU_TYPE if N_GPU == 1 else f"{GPU_TYPE}:{N_GPU}",
    scaledown_window=15 * MINUTES,
    timeout=60 * MINUTES,
    volumes={
        "/root/.cache/huggingface": hf_cache,
        "/root/.cache/vllm": vllm_cache,
    },
    secrets=[
        modal.Secret.from_name("huggingface-secret"),
        modal.Secret.from_name("vllm-api-key"),
    ],
)
@modal.web_server(port=8000, startup_timeout=20 * MINUTES)
def serve() -> None:
    """Launch vLLM's OpenAI-compatible server on port 8000."""
    import os
    import subprocess

    cmd = [
        "vllm", "serve", MODEL_NAME,
        "--host", "0.0.0.0",
        "--port", "8000",
        "--revision", MODEL_REVISION,
        "--tensor-parallel-size", str(N_GPU),
        "--max-model-len", str(MAX_MODEL_LEN),
        "--served-model-name", MODEL_NAME,
        "--disable-log-requests",
    ]

    api_key = os.environ.get("VLLM_API_KEY", "").strip()
    if api_key:
        cmd += ["--api-key", api_key]

    subprocess.Popen(cmd)


# ── 2. Embedding service (sentence-transformers, OpenAI-compatible /v1/embeddings)
@app.function(
    image=embed_image,
    volumes={EMBED_MODEL_DIR: embed_cache},
    secrets=[modal.Secret.from_name("vllm-api-key")],
    scaledown_window=15 * MINUTES,
    timeout=120,
)
@modal.asgi_app()
def embedding_api():
    import os
    from sentence_transformers import SentenceTransformer

    print(f"[startup] Loading embedding model: {EMBED_MODEL_ID}")
    model = SentenceTransformer(EMBED_MODEL_ID, cache_folder=EMBED_MODEL_DIR)
    embed_cache.commit()
    print("[startup] Embedding model ready ✓")

    web = FastAPI()

    @web.post("/v1/embeddings")
    async def create_embeddings(request: Request):
        auth = request.headers.get("Authorization", "")
        api_key = os.environ.get("VLLM_API_KEY", "")
        if api_key and auth != f"Bearer {api_key}":
            raise HTTPException(status_code=401, detail="Unauthorized")

        body  = await request.json()
        texts = body.get("input", [])
        if isinstance(texts, str):
            texts = [texts]

        vecs = model.encode(texts, normalize_embeddings=True).tolist()
        return {
            "object": "list",
            "data": [
                {"object": "embedding", "embedding": v, "index": i}
                for i, v in enumerate(vecs)
            ],
            "model": EMBED_MODEL_ID,
            "usage": {"prompt_tokens": 0, "total_tokens": 0},
        }

    return web
