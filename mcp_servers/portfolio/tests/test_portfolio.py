
from contextlib import asynccontextmanager

from mcp.shared.memory import create_connected_server_and_client_session

from mcp_servers.common import INPROC_USER
from mcp_servers.portfolio.server import mcp  # noqa: E402


@asynccontextmanager
async def connect():
    # in-memory MCP client; the caller identity travels in a context var (no HTTP headers in memory)
    tok = INPROC_USER.set("ai_ml")
    try:
        async with create_connected_server_and_client_session(mcp._mcp_server) as c:
            yield c
    finally:
        INPROC_USER.reset(tok)


async def test_lists_tools_resources_prompts():
    async with connect() as client:
        names = {t.name for t in (await client.list_tools()).tools}
        assert {"search_evidence", "get_case_study", "list_skills", "match_job_requirements", "find_projects"} <= names
        assert all(t.annotations.readOnlyHint for t in (await client.list_tools()).tools)
        templates = {t.uriTemplate for t in (await client.list_resource_templates()).resourceTemplates}
        assert {"portfolio://case/{case_id}", "portfolio://proposal/{proposal_id}"} <= templates
        assert "answer_screening_question" in {p.name for p in (await client.list_prompts()).prompts}


async def test_search_evidence_returns_typed_items():
    async with connect() as client:
        r = await client.call_tool("search_evidence", {"requirement": "Celery background task queue", "k": 3})
        items = r.structuredContent["items"]
        assert len(items) == 3 and {"evidence_id", "type", "source", "date", "outcome"} <= set(items[0])


async def test_filters_and_case_study_and_resource():
    async with connect() as client:
        r = await client.call_tool("search_evidence", {"requirement": "churn", "k": 5, "filters": {"type": ["proposal"], "outcome": ["won"]}})
        assert all(i["type"] == "proposal" and i["outcome"] == "won" for i in r.structuredContent["items"])
        cs = await client.call_tool("get_case_study", {"id": "ai_ml-cs-telco-churn"})
        assert "Telecom churn" in cs.structuredContent["title"]
        res = await client.read_resource("portfolio://case/ai_ml-cs-telco-churn")
        assert "Telecom churn" in res.contents[0].text


async def test_tenant_isolation():
    async with connect() as client:
        r = await client.call_tool("get_case_study", {"id": "fullstack-cs-saas-billing"})
        assert r.isError  # another tenant's evidence is invisible


async def test_requirement_matrix_and_graph():
    async with connect() as client:
        r = await client.call_tool("match_job_requirements", {
            "job_title": "Churn model", "job_description": "Requirements:\n- XGBoost\n- MLflow\n- Unity", "requirements": []})
        reqs = {m["requirement"]: m for m in r.structuredContent["requirements"]}
        assert reqs["XGBoost"]["evidence"]
        g = await client.call_tool("find_projects", {"skill": "xgboost"})
        assert any(p["project"] == "Telecom churn model" for p in g.structuredContent["projects"])
