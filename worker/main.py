"""Arq worker: `arq worker.main.WorkerSettings`.

Schedules (E1): `tick` runs every minute and fans out per user; each saved search still only runs when
its own interval has elapsed (and in live Upwork mode never more often than
marketplace.live_poll_minutes, see docs/RUNBOOK.md). Long agent runs happen here, never in web requests.
"""

from __future__ import annotations

import os

from arq import cron
from arq.connections import RedisSettings

from shared.tracing import setup_tracing
from worker.tasks import TASKS, tick


async def startup(ctx):
    setup_tracing("gigbid-worker")


class WorkerSettings:
    functions = list(TASKS.values())
    cron_jobs = [cron(tick, minute=None, run_at_startup=True, unique=True)]  # every minute
    redis_settings = RedisSettings.from_dsn(os.getenv("REDIS_URL", "redis://localhost:6379/0"))
    on_startup = startup
    max_jobs = int(os.getenv("WORKER_CONCURRENCY", "4"))
    job_timeout = 900
    keep_result = 0  # results live in the DB; a kept result would block re-enqueueing the same _job_id (dedup is only for queued/running jobs)
    allow_abort_jobs = True
