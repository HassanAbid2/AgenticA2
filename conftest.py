"""Test-wide environment: isolated SQLite DB, in-process GigSim without chaos, offline model profile."""

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="gigbid-test-")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_tmp}/test.db".replace("\\", "/"))
os.environ.setdefault("CHECKPOINT_DB", f"{_tmp}/checkpoints.db")
os.environ["GIGSIM_INPROCESS"] = "1"
os.environ["GIGSIM_ERROR_RATE"] = "0"
os.environ["GIGSIM_TIME_SCALE"] = "1000"
os.environ["GIGSIM_RATE_LIMIT_PER_MIN"] = "100000"
os.environ.setdefault("MODEL_PROFILE", "offline")
os.environ.setdefault("APP_SECRET_KEY", "test-secret")
