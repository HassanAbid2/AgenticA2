"""Prompt templates a freelancer would actually pick in Claude Desktop / Cursor.
Prompt text lives in agent/prompts/ like every other prompt in the repo."""

from __future__ import annotations

from pathlib import Path

PROMPTS = Path(__file__).resolve().parents[2] / "agent" / "prompts"


def _tpl(name: str, **kw) -> str:
    return (PROMPTS / f"{name}.md").read_text(encoding="utf-8").format(**kw)


def register(mcp):
    @mcp.prompt(title="Answer a screening question from my portfolio")
    def answer_screening_question(question: str, job_title: str = "") -> str:
        """Draft an answer to a client's screening question using only evidence from my portfolio."""
        return _tpl("mcp_screening_answer", question=question, job_title=job_title)

    @mcp.prompt(title="Is this job a fit for me?")
    def fit_check(job_post: str) -> str:
        """Map each requirement of a pasted job post to portfolio evidence and say bid or skip."""
        return _tpl("mcp_fit_check", job_post=job_post)

    @mcp.prompt(title="Turn a project into a case study")
    def case_study_from_project(project: str) -> str:
        """Write a short, verifiable case study for one project using its README, code and reviews."""
        return _tpl("mcp_case_study", project=project)

    return mcp
