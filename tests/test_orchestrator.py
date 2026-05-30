import pytest
from sqlalchemy import select

from fpl_engine.db.models import run_registry
from fpl_engine.orchestrator import Job, Orchestrator
from fpl_engine.orchestrator.registry import RunRegistry


def _registry(sm):
    return RunRegistry(sm)


def test_run_once_records_success(sm):
    orch = Orchestrator(registry=_registry(sm))
    orch.register(Job("noop", lambda: 42))

    assert orch.run_once("noop") == 42

    with sm() as s:
        row = s.execute(select(run_registry)).one()
    assert row.job_name == "noop"
    assert row.status == "success"
    assert row.finished_at is not None
    assert row.error is None


def test_run_once_records_failure(sm):
    orch = Orchestrator(registry=_registry(sm))

    def boom():
        raise ValueError("kaboom")

    orch.register(Job("boom", boom))

    with pytest.raises(ValueError):
        orch.run_once("boom")

    with sm() as s:
        row = s.execute(select(run_registry)).one()
    assert row.status == "failed"
    assert "kaboom" in row.error


def test_event_trigger_records_reason(sm):
    orch = Orchestrator(registry=_registry(sm))
    orch.register(Job("recompute", lambda: "done"))

    orch.trigger("recompute", reason="odds_steam")

    with sm() as s:
        row = s.execute(select(run_registry)).one()
    assert row.meta["trigger"] == "odds_steam"
