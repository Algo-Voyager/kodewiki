"""Shared Inngest client — imported by server.py and agent.py.

Keep this module free of heavy imports so both the FastAPI server and the
standalone agent CLI can load it without pulling in the full web stack.
"""
from __future__ import annotations

import logging

import inngest
from dotenv import load_dotenv

load_dotenv()

inngest_client = inngest.Inngest(
    app_id="repomind",
    logger=logging.getLogger("uvicorn"),
    is_production=False,
)
