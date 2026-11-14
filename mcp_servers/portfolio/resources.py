"""Resource templates so a host (Claude Desktop, Cursor, GigBid) can load full portfolio items."""

from __future__ import annotations

import json

from mcp_servers.common import caller
from mcp_servers.portfolio.tools import _index, owners_for


def _doc(evidence_id: str) -> str:
    chunks = [c for c in _index().docs_for(owners_for(caller(None))) if c.evidence_id == evidence_id]
    if not chunks:
        raise ValueError(f"unknown evidence id {evidence_id}")
    c = chunks[0]
    head = f"# {c.title}\n\ntype: {c.type} | project: {c.project or '-'} | date: {c.date or '-'}" + (
        f" | outcome: {c.outcome}" if c.outcome else "") + f" | source: {c.source}\n\n"
    return head + "\n\n".join(x.text for x in chunks)


def register(mcp):
    @mcp.resource("portfolio://case/{case_id}", mime_type="text/markdown", description="A case study by evidence id")
    def case(case_id: str) -> str:
        return _doc(case_id)

    @mcp.resource("portfolio://proposal/{proposal_id}", mime_type="text/markdown",
                  description="A past proposal with its outcome (won / replied / ignored)")
    def proposal(proposal_id: str) -> str:
        return _doc(proposal_id)

    @mcp.resource("portfolio://evidence/{evidence_id}", mime_type="text/markdown", description="Any evidence item")
    def evidence(evidence_id: str) -> str:
        return _doc(evidence_id)

    @mcp.resource("portfolio://index", mime_type="application/json", description="All evidence items (id, type, title)")
    def index() -> str:
        seen = {}
        for c in _index().docs_for(owners_for(caller(None))):
            seen.setdefault(c.evidence_id, {"id": c.evidence_id, "type": c.type, "title": c.title, "project": c.project})
        return json.dumps(list(seen.values()), indent=1)

    return mcp
