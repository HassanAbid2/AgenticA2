"""Repo ingestion through the official GitHub MCP server (third-party server, see docs/TOOLS.md).

GigBid never calls the GitHub REST API or scrapes github.com directly: it asks the GitHub MCP server
for `search_repositories` and `get_file_contents`, then feeds README + code files to the indexer.

    GITHUB_PERSONAL_ACCESS_TOKEN=... python -m rag.ingest.github_mcp <github-login> --owner user-1 --persona ai_ml
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os

from rag.ingest.loaders import CODE_EXT, Doc
from rag.skills import extract_skills

GITHUB_MCP_URL = os.getenv("GITHUB_MCP_URL", "https://api.githubcopilot.com/mcp/")


def _connection():
    token = os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"]
    if os.getenv("GITHUB_MCP_DOCKER"):  # local stdio server instead of the hosted endpoint
        return {"transport": "stdio", "command": "docker",
                "args": ["run", "-i", "--rm", "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", "ghcr.io/github/github-mcp-server"],
                "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": token}}
    return {"transport": "streamable_http", "url": GITHUB_MCP_URL, "headers": {"Authorization": f"Bearer {token}"}}


def _text(result) -> str:
    """MCP tool results arrive as content blocks; flatten to text (decode base64 file payloads)."""
    if isinstance(result, list):
        parts = []
        for r in result:
            parts.append(r.get("text", "") if isinstance(r, dict) else getattr(r, "text", str(r)))
        result = "\n".join(parts)
    try:
        obj = json.loads(result)
        if isinstance(obj, dict) and obj.get("encoding") == "base64":
            return base64.b64decode(obj["content"]).decode("utf-8", "ignore")
    except (ValueError, TypeError):
        pass
    return str(result)


async def fetch_repos(login: str, owner: str, persona: str, max_repos: int = 10, max_files: int = 4) -> list[Doc]:
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient({"github": _connection()})
    tools = {t.name: t for t in await client.get_tools(server_name="github")}
    found = json.loads(_text(await tools["search_repositories"].ainvoke({"query": f"user:{login} fork:false", "perPage": max_repos})))
    docs: list[Doc] = []
    for repo in (found.get("items") or [])[:max_repos]:
        name = repo["name"]
        args = {"owner": login, "repo": name}
        try:
            readme = _text(await tools["get_file_contents"].ainvoke(args | {"path": "README.md"}))
        except Exception:  # noqa: BLE001 - repo without README
            readme = repo.get("description") or ""
        docs.append(Doc(f"{owner}-gh-{name}-readme", owner, persona, "readme", f"{name} README", readme,
                        project=name, skills=extract_skills(readme), source=repo.get("html_url", "")))
        listing = json.loads(_text(await tools["get_file_contents"].ainvoke(args | {"path": "/"})) or "[]")
        files = [f["path"] for f in listing if isinstance(f, dict) and f.get("type") == "file"
                 and os.path.splitext(f["path"])[1].lower() in CODE_EXT][:max_files]
        for path in files:
            code = _text(await tools["get_file_contents"].ainvoke(args | {"path": path}))
            docs.append(Doc(f"{owner}-gh-{name}-{path.replace('/', '_')}", owner, persona, "code", f"{name}/{path}",
                            code[:8000], project=name, skills=extract_skills(code, code=True),
                            source=f"{repo.get('html_url', '')}/blob/HEAD/{path}"))
    return docs


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("login")
    ap.add_argument("--owner", required=True)
    ap.add_argument("--persona", default="own")
    a = ap.parse_args()
    from rag.index.store import get_index

    docs = asyncio.run(fetch_repos(a.login, a.owner, a.persona))
    for scheme in ("structured", "contextual", "naive"):
        print(scheme, get_index(scheme).upsert_docs(docs))
