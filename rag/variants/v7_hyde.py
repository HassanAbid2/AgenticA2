"""V7 HyDE: retrieve with a hypothetical ideal proposal paragraph written for the job (vague posts)."""

from __future__ import annotations

from rag.requirements import extract_requirements

CONFIG = {"query": "hyde"}


def template_hypothesis(job: dict) -> str:
    """Offline fallback when no LLM is configured."""
    reqs = extract_requirements(job)
    return (f"I recently built a project very similar to this: {job.get('title', '')}. "
            f"I delivered {'; '.join(reqs[:4])}, and measured the results for the client.")


def make_hyde_fn(llm_text):
    """llm_text(prompt_name, **vars) -> str. Returns a function job -> hypothetical proposal."""

    def hyde(job: dict) -> str:
        try:
            out = llm_text("hyde", job_title=job.get("title", ""), job_description=job.get("description", "")[:2500])
            return out.strip() or template_hypothesis(job)
        except Exception:  # noqa: BLE001 - retrieval must not fail because the LLM did
            return template_hypothesis(job)

    return hyde
