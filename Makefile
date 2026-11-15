.PHONY: install dev test e2e eval eval-llm seed demo lint up down graphs tools openapi

PY ?= .venv/Scripts/python
ifeq ($(OS),)
PY = .venv/bin/python
endif

install:            ## Python + web dependencies
	uv sync --extra dev
	cd apps/web && npm ci

seed:               ## regenerate the synthetic world (deterministic) and build the indexes
	$(PY) -m scripts.generate_synthetic_data
	$(PY) -m rag.ingest.build

dev:                ## single-process stack: API + web + in-process GigSim/MCP on :8000
	cd apps/web && npm run build
	$(PY) -m scripts.dev_single

up:                 ## full stack in Docker (web on :8080, Phoenix on :6006)
	docker compose -f infra/docker-compose.yml --env-file .env up --build -d

down:
	docker compose -f infra/docker-compose.yml down

test:               ## unit, contract, MCP, integration
	$(PY) -m pytest -q

e2e:                ## Playwright suite (starts its own server)
	cd apps/web && npx playwright test

lint:
	$(PY) -m ruff check .
	$(PY) -m scripts.ci_checks

eval:               ## no-LLM evals: retrieval variants, decisions, smoke gate (writes evals/results/*.json)
	MODEL_PROFILE=offline $(PY) -m evals.runners.rag_eval
	MODEL_PROFILE=offline $(PY) -m evals.runners.decision_eval --profile offline
	MODEL_PROFILE=offline $(PY) -m evals.runners.smoke --jobs 30

eval-llm:           ## LLM evals on Groq (resumable: rerun daily on the free tier until complete)
	$(PY) -m evals.runners.decision_eval --profile open --n 15
	$(PY) -m evals.runners.proposal_eval
	$(PY) -m evals.runners.injection_eval
	$(PY) -m evals.runners.multiagent_compare
	$(PY) -m evals.runners.tool_granularity
	$(PY) -m evals.runners.ab_experiment
	$(PY) -m evals.runners.results_table

demo:               ## reviewer login: reviewer@gigbid.dev / $$REVIEWER_PASSWORD
	$(PY) -m scripts.dev_single

graphs:             ## render both graphs from code
	$(PY) -m agent.runner

tools:              ## regenerate docs/TOOLS.md from the MCP schema snapshot
	$(PY) -m scripts.gen_tools_md

openapi:            ## regenerate the typed TS client from FastAPI's OpenAPI schema
	$(PY) -m scripts.export_openapi
	cd apps/web && npm run gen:api
