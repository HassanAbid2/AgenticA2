"""GigBid Portfolio MCP server (read-only).

    python -m mcp_servers.portfolio.server            # stdio (Claude Desktop / Cursor)
    python -m mcp_servers.portfolio.server --http     # streamable HTTP on :8101 with bearer auth

Standalone use: set PORTFOLIO_DIR to a folder (case_studies/*.md, repos/, reviews.json,
proposals.jsonl, cv.pdf) and it is indexed on start-up. See mcp_servers/portfolio/README.md.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from mcp_servers.common import run, server_kwargs
from mcp_servers.portfolio import prompts, resources, tools

PORT = int(os.getenv("PORTFOLIO_MCP_PORT", "8101"))

mcp = FastMCP(
    "gigbid-portfolio",
    instructions=("Read-only access to one freelancer's portfolio: case studies, repos and code, client reviews and "
                  "past proposals with outcomes. Use search_evidence to prove a single requirement, "
                  "match_job_requirements for a whole job, get_case_study for full text. Never invent experience: "
                  "if nothing relevant is returned, say so."),
    **server_kwargs(PORT, require_auth="--http" in sys.argv),
)
tools.register(mcp)
resources.register(mcp)
prompts.register(mcp)


def _standalone_ingest():
    folder = os.getenv("PORTFOLIO_DIR")
    if not folder:
        return
    # installed via uvx: keep the index next to the user's data, not inside site-packages (set before importing rag)
    os.environ.setdefault("GIGBID_PROCESSED_DIR", str(Path.home() / ".gigbid" / "processed"))
    os.environ.setdefault("GIGBID_MODELS_DIR", str(Path.home() / ".gigbid" / "models"))
    from rag.index.store import get_index
    from rag.ingest.loaders import load_persona

    owner = os.environ.setdefault("PORTFOLIO_OWNER", "local")
    docs = load_persona(Path(folder), owner=owner)
    for scheme in ("structured", "contextual", "naive"):
        get_index(scheme).upsert_docs(docs)


def main():
    _standalone_ingest()
    run(mcp, PORT)


if __name__ == "__main__":
    main()
