# GigBid ingest (build context: repo root)
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_LINK_MODE=copy GIGBID_MODELS_DIR=/models PATH="/app/.venv/bin:$PATH"
WORKDIR /app
RUN pip install --no-cache-dir uv==0.11.28
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY . .
RUN uv sync --frozen --no-dev
RUN useradd -u 1000 -m app && mkdir -p /models /app/var /app/data/processed && chown -R app /models /app/var /app/data/processed
USER app
CMD ["python", "-m", "rag.ingest.build"]
