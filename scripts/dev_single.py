"""Single-process local run (no Docker): API + web build + in-process GigSim and MCP servers + inline tasks.

    python -m scripts.dev_single          # http://localhost:8000  (reviewer@gigbid.dev / reviewer-local-only)
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

for k, v in {"MCP_INPROCESS": "1", "GIGSIM_INPROCESS": "1", "TASK_MODE": "inline", "GIGSIM_ERROR_RATE": "0.02",
             "MARKETPLACE_RPM": "600", "GIGSIM_RATE_LIMIT_PER_MIN": "600", "GIGSIM_TIME_SCALE": "10"}.items():
    os.environ.setdefault(k, v)

import uvicorn  # noqa: E402

if __name__ == "__main__":
    uvicorn.run("apps.api.main:app", host="127.0.0.1", port=int(os.getenv("PORT", "8000")), log_level="info")
