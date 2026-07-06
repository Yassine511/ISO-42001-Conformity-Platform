"""Unit tests for the shared assessment runner (app.pipeline.runner).

Synchronous execution against the test session factory (no threads except the
launch() registry tests, which stub the run itself): the run contract is the
persisted Assessment row, resume aggregation is authoritative, cancellation is
cooperative, and the stream (on_node) path matches invoke exactly.
"""

import pytest
from sqlalchemy import select

from app.models import Assessment, Finding
from app.pipeline import llm as llm_service
from app.pipeline import runner
from app.pipeline.graph import create_assessment, run_requirement
from app.pipeline.state import AssessmentStatus
from tests.test_pipeline import FakeLLM, _missing_draft, _valid_draft, env  # noqa: F401


def _use(fake: FakeLLM) -> FakeLLM:
    llm_service.set_provider(fake)
    return fake


def _row(session_factory, assessment_id) -> Assessment:
    db = session_factory()
    try:
        return db.get(Assessment, assessment_id)
    finally:
        db.close()


def test_run_reads_contract_from_the_row(env, monkeypatch):  # noqa: F811
    """requirement_ids and retrieval_k come from PostgreSQL — a caller cannot
    run with values that disagree with the persisted assessment."""
    session_factory, org_id = env
    _use(FakeLLM([_valid_draft()]))
    aid = create_assessment(session_factory, org_id, ["A.9.2"], k=3)

    seen: dict = {}
    real = runner.run_requirement

    def spy(sf, a, rid, **kwargs):
        seen["k"] = kwargs.get("k")
        return real(sf, a, rid, **kwargs)

    monkeypatch.setattr(runner, "run_requirement", spy)
    run = runner.run_assessment(session_factory, aid)
    assert seen["k"] == 3
    assert run.status == "COMPLETED" and run.done == 1 and run.total == 1
    assert run.verified == 1 and run.abstained == 0


def test_mixed_outcomes_complete(env):  # noqa: F811
    session_factory, org_id = env
    _use(FakeLLM([_valid_draft(), _missing_draft(clause="A.4.5")]))
    aid = create_assessment(session_factory, org_id, ["A.9.2", "A.4.5"])
    run = runner.run_assessment(session_factory, aid)
    assert run.status == "COMPLETED"
    assert run.verified == 1 and run.abstained == 1 and run.infra_abstains == 0
    assert _row(session_factory, aid).status == "COMPLETED"


def test_all_infrastructure_failures_fail_the_run(env):  # noqa: F811
    session_factory, org_id = env
    _use(FakeLLM([None, None]))  # every provider call fails
    aid = create_assessment(session_factory, org_id, ["A.9.2", "A.4.5"])
    run = runner.run_assessment(session_factory, aid)
    assert run.status == "FAILED"
    assert run.infra_abstains == 2
    row = _row(session_factory, aid)
    assert row.status == "FAILED" and "panne LLM" in row.error


def test_resume_aggregates_existing_findings(env):  # noqa: F811
    """A resumed run is judged on ALL its findings: old infra abstentions plus
    one new evidentiary finding -> COMPLETED; progress starts at the existing
    finding count."""
    session_factory, org_id = env
    aid = create_assessment(session_factory, org_id, ["A.9.2", "A.4.5"])
    # first requirement executed before a "crash": infra abstention
    _use(FakeLLM([None]))
    run_requirement(session_factory, aid, "A.9.2")
    # resume with a working provider for the remaining requirement
    _use(FakeLLM([_valid_draft(clause="A.4.5")]))
    progress: list = []
    run = runner.run_assessment(
        session_factory,
        aid,
        on_progress=lambda rid, node, done, total: progress.append((rid, node, done, total)),
    )
    assert run.status == "COMPLETED"  # one evidentiary finding -> not all-infra
    assert run.done == 2 and run.verified == 1 and run.infra_abstains == 1
    # progress counted the pre-existing finding from the start
    assert progress[0] == ("A.4.5", "retrieve", 1, 2)


def test_resume_all_infra_old_and_new_fails(env):  # noqa: F811
    session_factory, org_id = env
    aid = create_assessment(session_factory, org_id, ["A.9.2", "A.4.5"])
    _use(FakeLLM([None]))
    run_requirement(session_factory, aid, "A.9.2")
    _use(FakeLLM([None]))
    run = runner.run_assessment(session_factory, aid)
    assert run.status == "FAILED"
    assert run.infra_abstains == 2


def test_cancel_before_any_requirement(env):  # noqa: F811
    session_factory, org_id = env
    _use(FakeLLM([]))
    aid = create_assessment(session_factory, org_id, ["A.9.2"])
    db = session_factory()
    db.get(Assessment, aid).cancel_requested = True
    db.commit()
    db.close()
    run = runner.run_assessment(session_factory, aid)
    assert run.status == "FAILED" and run.error == runner.CANCELLED_ERROR
    assert run.done == 0
    assert _row(session_factory, aid).error == runner.CANCELLED_ERROR


def test_cancel_during_last_requirement_wins_over_completed(env, monkeypatch):  # noqa: F811
    """The re-check immediately before finalization: a cancel landing while
    the final requirement executes must finalize FAILED, not COMPLETED."""
    session_factory, org_id = env
    _use(FakeLLM([_valid_draft()]))
    aid = create_assessment(session_factory, org_id, ["A.9.2"])
    real = runner.run_requirement

    def cancel_during(sf, a, rid, **kwargs):
        result = real(sf, a, rid, **kwargs)
        db = sf()
        db.get(Assessment, a).cancel_requested = True
        db.commit()
        db.close()
        return result

    monkeypatch.setattr(runner, "run_requirement", cancel_during)
    run = runner.run_assessment(session_factory, aid)
    assert run.status == "FAILED" and run.error == runner.CANCELLED_ERROR
    assert run.done == 1  # the finding itself was persisted


def test_operational_failure_keeps_running_with_note(env, monkeypatch):  # noqa: F811
    session_factory, org_id = env
    _use(FakeLLM([_valid_draft()]))
    aid = create_assessment(session_factory, org_id, ["A.9.2", "A.4.5"])
    real = runner.run_requirement

    def boom_on_second(sf, a, rid, **kwargs):
        if rid == "A.4.5":
            raise RuntimeError("panne réseau")
        return real(sf, a, rid, **kwargs)

    monkeypatch.setattr(runner, "run_requirement", boom_on_second)
    run = runner.run_assessment(session_factory, aid)
    assert run.status == "RUNNING"  # incomplete coverage stays resumable
    assert run.operational_failures == 1 and run.done == 1
    row = _row(session_factory, aid)
    assert row.status == "RUNNING" and "A.4.5" in row.error


def test_on_progress_exception_never_aborts(env):  # noqa: F811
    session_factory, org_id = env
    _use(FakeLLM([_valid_draft()]))
    aid = create_assessment(session_factory, org_id, ["A.9.2"])

    def bad_progress(*args):
        raise RuntimeError("ui gone")

    run = runner.run_assessment(session_factory, aid, on_progress=bad_progress)
    assert run.status == "COMPLETED"


def test_manifestless_row_is_refused(env):  # noqa: F811
    session_factory, org_id = env
    aid = create_assessment(session_factory, org_id, requirement_ids=None)
    with pytest.raises(ValueError, match="manifeste incomplet"):
        runner.run_assessment(session_factory, aid)


def test_stream_path_matches_invoke_path(env):  # noqa: F811
    """on_node uses graph.stream; the persisted finding must be identical to
    the invoke path (same FakeLLM script, two assessments)."""
    session_factory, org_id = env
    from app.pipeline.graph import finalize_assessment

    _use(FakeLLM([_valid_draft()]))
    aid1 = create_assessment(session_factory, org_id, ["A.9.2"])
    r1 = run_requirement(session_factory, aid1, "A.9.2")  # invoke path
    finalize_assessment(session_factory, aid1, AssessmentStatus.COMPLETED)

    _use(FakeLLM([_valid_draft()]))
    aid2 = create_assessment(session_factory, org_id, ["A.9.2"])
    nodes: list[str] = []
    r2 = run_requirement(
        session_factory, aid2, "A.9.2", on_node=nodes.append
    )  # stream path

    assert nodes == ["retrieve", "judge", "verify"]
    db = session_factory()
    f1 = db.scalars(select(Finding).where(Finding.assessment_id == aid1)).one()
    f2 = db.scalars(select(Finding).where(Finding.assessment_id == aid2)).one()
    db.close()
    for field in (
        "status",
        "verdict",
        "policy_quote",
        "clause_ref",
        "confidence",
        "rationale",
        "match_start",
        "match_end",
        "match_method",
        "match_score",
        "attempts",
        "abstain_reason",
    ):
        assert getattr(f1, field) == getattr(f2, field), field
    assert r1.status == r2.status == "VERIFIED"


def test_launch_registry_cleanup_on_crash(env, monkeypatch):  # noqa: F811
    """The thread wrapper must clean _THREADS/PROGRESS even when the run
    crashes, and keep the row resumable via note_assessment_error."""
    session_factory, org_id = env
    noted: list = []

    def boom(sf, aid, **kwargs):
        runner.PROGRESS[aid] = {"requirement_id": "A.9.2", "node": "judge", "done": 0, "total": 1}
        raise RuntimeError("crash")

    monkeypatch.setattr(runner, "run_assessment", boom)
    monkeypatch.setattr(
        runner, "note_assessment_error", lambda sf, aid, err: noted.append((aid, err))
    )
    assert runner.launch(session_factory, "fake-id") is True
    runner._THREADS["fake-id"].join(timeout=5)
    assert not runner.is_running_locally("fake-id")
    assert "fake-id" not in runner.PROGRESS
    assert noted == [("fake-id", "crash")]


def test_launch_refuses_double_start(env, monkeypatch):  # noqa: F811
    import threading

    session_factory, _ = env
    release = threading.Event()
    monkeypatch.setattr(runner, "run_assessment", lambda sf, aid, **kw: release.wait(5))
    assert runner.launch(session_factory, "aid-1") is True
    try:
        assert runner.launch(session_factory, "aid-1") is False
        assert runner.is_running_locally("aid-1")
    finally:
        release.set()
        runner._THREADS.get("aid-1", threading.current_thread()).join(timeout=5)
