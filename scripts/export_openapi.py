"""Writes apps/web/openapi.json from the FastAPI app (input to the generated TypeScript client)."""

import json
import os
from pathlib import Path

os.environ.setdefault("SEED_REVIEWER", "0")
from apps.api.main import app  # noqa: E402

out = Path(__file__).resolve().parents[1] / "apps" / "web" / "openapi.json"
out.write_text(json.dumps(app.openapi(), indent=1) + "\n", encoding="utf-8", newline="\n")
print(out, len(app.openapi()["paths"]), "paths")
