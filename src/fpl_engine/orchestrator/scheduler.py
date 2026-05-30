"""Orchestrator: cron-like scheduling + event triggers over the run registry.

Jobs are plain callables. ``run_once`` executes a job synchronously inside a
registry-tracked run (used by the CLI and by event triggers); ``start`` runs
the APScheduler loop for cron jobs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from ..logging_setup import get_logger
from .registry import RunRegistry

log = get_logger(__name__)

JobFn = Callable[..., Any]


@dataclass
class Job:
    name: str
    fn: JobFn
    cron: str | None = None  # e.g. "30 1 * * *" (price-change watch ~01:30 UK)
    kwargs: dict[str, Any] = field(default_factory=dict)


class Orchestrator:
    def __init__(self, registry: RunRegistry | None = None):
        self._registry = registry or RunRegistry()
        self._jobs: dict[str, Job] = {}
        self._scheduler: BackgroundScheduler | None = None

    def register(self, job: Job) -> None:
        if job.name in self._jobs:
            raise ValueError(f"duplicate job: {job.name}")
        self._jobs[job.name] = job

    def run_once(self, name: str, **extra: Any) -> Any:
        """Run a registered job now, recording the run. Returns the job result."""
        job = self._jobs[name]
        merged = {**job.kwargs, **extra}
        with self._registry.run(job.name, meta={"trigger": "manual", "kwargs": list(merged)}):
            return job.fn(**merged)

    def trigger(self, name: str, reason: str, **extra: Any) -> Any:
        """Event-driven trigger (price change, lineup, odds steam, post-match)."""
        job = self._jobs[name]
        merged = {**job.kwargs, **extra}
        with self._registry.run(job.name, meta={"trigger": reason, "kwargs": list(merged)}):
            return job.fn(**merged)

    def start(self) -> BackgroundScheduler:
        """Start cron scheduling for all jobs that declare a cron expression."""
        self._scheduler = BackgroundScheduler(timezone="Europe/London")
        for job in self._jobs.values():
            if job.cron:
                self._scheduler.add_job(
                    lambda n=job.name: self.run_once(n),
                    trigger=CronTrigger.from_crontab(job.cron, timezone="Europe/London"),
                    id=job.name,
                    name=job.name,
                )
                log.info("scheduled job", extra={"job": job.name, "cron": job.cron})
        self._scheduler.start()
        return self._scheduler
