"""Run registry: every job execution is recorded with status and timing."""

from __future__ import annotations

import traceback
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from sqlalchemy import update
from sqlalchemy.orm import Session, sessionmaker

from ..db.engine import get_sessionmaker
from ..db.models import run_registry
from ..logging_setup import get_logger

log = get_logger(__name__)


class RunRegistry:
    def __init__(self, sm: sessionmaker[Session] | None = None):
        self._sm = sm or get_sessionmaker()

    def _start(self, job_name: str, meta: dict[str, Any]) -> int:
        with self._sm() as s:
            run_id = s.execute(
                run_registry.insert()
                .values(job_name=job_name, status="running", meta=meta)
                .returning(run_registry.c.id)
            ).scalar_one()
            s.commit()
            return int(run_id)

    def _finish(self, run_id: int, status: str, error: str | None) -> None:
        with self._sm() as s:
            s.execute(
                update(run_registry)
                .where(run_registry.c.id == run_id)
                .values(status=status, finished_at=datetime.now(timezone.utc), error=error)
            )
            s.commit()

    @contextmanager
    def run(self, job_name: str, meta: dict[str, Any] | None = None) -> Iterator[int]:
        run_id = self._start(job_name, meta or {})
        log.info("job started", extra={"job": job_name, "run_id": run_id})
        try:
            yield run_id
        except Exception as exc:
            self._finish(run_id, "failed", f"{exc}\n{traceback.format_exc()}")
            log.error("job failed", extra={"job": job_name, "run_id": run_id, "error": str(exc)})
            raise
        else:
            self._finish(run_id, "success", None)
            log.info("job finished", extra={"job": job_name, "run_id": run_id})
