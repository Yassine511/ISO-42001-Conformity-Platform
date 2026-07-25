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


def test_coverage_note_has_no_dangling_separator(env, monkeypatch):  # noqa: F811
    """Incomplete coverage with NO operational failure and NO infra abstention:
    the note is the coverage clause alone, never prefixed by a bare ' ; '."""
    session_factory, org_id = env
    _use(FakeLLM([_valid_draft()]))
    aid = create_assessment(session_factory, org_id, ["A.9.2", "A.4.5"])
    real = runner.run_requirement

    def skip_second(sf, a, rid, **kwargs):
        # succeeds without persisting a finding -> uncovered, but not a failure
        return real(sf, a, rid, **kwargs) if rid == "A.9.2" else {"finding": None}

    monkeypatch.setattr(runner, "run_requirement", skip_second)
    run = runner.run_assessment(session_factory, aid)
    assert run.status == "RUNNING" and run.operational_failures == 0
    error = _row(session_factory, aid).error
    assert error.startswith("1 exigence(s) sans constat : A.4.5")


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


def test_finalize_terminal_states_are_immutable(env):  # noqa: F811
    """A caller whose RUNNING check raced a concurrent finalization (abandon
    endpoint vs runner finishing) must not rewrite the outcome."""
    from app.pipeline.graph import finalize_assessment

    session_factory, org_id = env
    _use(FakeLLM([_valid_draft()]))
    aid = create_assessment(session_factory, org_id, ["A.9.2"])
    run = runner.run_assessment(session_factory, aid)
    assert run.status == "COMPLETED"
    # late cancellation loses: no write, False returned, row untouched
    assert (
        finalize_assessment(
            session_factory, aid, AssessmentStatus.FAILED, error="Abandonnée par l'utilisateur."
        )
        is False
    )
    row = _row(session_factory, aid)
    assert row.status == "COMPLETED" and row.error is None


def test_persisted_findings_are_write_once(env):  # noqa: F811
    """First writer wins at the persistence boundary: a duplicate execution
    (checkpoint re-run, or two workers resuming the same assessment) must
    never rewrite the AI draft a human may already be reviewing."""
    from app.pipeline.nodes import _persist_finding

    session_factory, org_id = env
    _use(FakeLLM([_valid_draft()]))
    aid = create_assessment(session_factory, org_id, ["A.9.2"])
    first = run_requirement(session_factory, aid, "A.9.2")
    assert first.status == "VERIFIED"

    state = {"assessment_id": aid, "requirement_id": "A.9.2", "retrieved": []}
    conflicting = {
        "status": "ABSTAINED",
        "verdict": "missing",
        "rationale": "duplicate execution",
        "abstain_reason": "verification_failed",
        "attempts": 2,
        "match": None,
    }
    returned_id = _persist_finding(session_factory, state, conflicting)
    assert returned_id == first.finding_id  # same row, no duplicate
    db = session_factory()
    row = db.get(Finding, first.finding_id)
    db.close()
    assert row.status == "VERIFIED"  # untouched
    assert row.verdict == first.verdict
    assert row.rationale == first.rationale
    assert row.attempts == first.attempts


def test_terminal_metadata_is_immutable(env):  # noqa: F811
    """A finalized row's metadata is canonical: a late cancel flag is cleared
    by the winning finalization, and a late runner crash cannot stamp its
    error onto a terminal assessment."""
    from app.pipeline.graph import note_assessment_error

    session_factory, org_id = env
    _use(FakeLLM([_valid_draft()]))
    aid = create_assessment(session_factory, org_id, ["A.9.2"])

    # cancel requested during the last requirement, but finalization wins the
    # race window after the re-check: honoured -> FAILED cancelled, flag reset
    run = runner.run_assessment(session_factory, aid)
    assert run.status == "COMPLETED"
    row = _row(session_factory, aid)
    assert row.cancel_requested is False

    # late crash after finalization: error must not be written
    note_assessment_error(session_factory, aid, "late runner crash")
    row = _row(session_factory, aid)
    assert row.status == "COMPLETED" and row.error is None


def test_finalize_clears_pending_cancel_flag(env):  # noqa: F811
    """The flag is a REQUEST, meaningless once terminal: even when a cancel
    lands in the window between the runner's re-check and its finalize commit,
    the terminal row never persists cancel_requested=true."""
    from app.pipeline.graph import finalize_assessment

    session_factory, org_id = env
    _use(FakeLLM([]))
    aid = create_assessment(session_factory, org_id, ["A.9.2"])
    db = session_factory()
    db.get(Assessment, aid).cancel_requested = True
    db.commit()
    db.close()
    assert finalize_assessment(session_factory, aid, AssessmentStatus.COMPLETED) is True
    row = _row(session_factory, aid)
    assert row.status == "COMPLETED" and row.cancel_requested is False


def test_losing_duplicate_execution_returns_canonical_payload(env):  # noqa: F811
    """First-writer-wins must also canonicalize the LOSING execution's
    payload: callbacks/CLI/evaluators consuming the returned finding can never
    disagree with PostgreSQL."""
    from app.pipeline.nodes import _persist_finding

    session_factory, org_id = env
    _use(FakeLLM([_valid_draft()]))
    aid = create_assessment(session_factory, org_id, ["A.9.2"])
    first = run_requirement(session_factory, aid, "A.9.2")
    assert first.status == "VERIFIED"

    state = {"assessment_id": aid, "requirement_id": "A.9.2", "retrieved": []}
    losing = {
        "status": "ABSTAINED",
        "verdict": "missing",
        "rationale": "duplicate execution",
        "abstain_reason": "verification_failed",
        "attempts": 2,
        "match": None,
    }
    _persist_finding(session_factory, state, losing)
    # the dict was rewritten in place to the stored row's content
    assert losing["finding_id"] == first.finding_id
    assert losing["status"] == "VERIFIED"
    assert losing["verdict"] == first.verdict
    assert losing["rationale"] == first.rationale
    assert losing["attempts"] == first.attempts
    assert losing["match"] is not None
    assert losing["match"]["method"] == "exact"
    assert losing["canonical_from_row"] is True


def test_losing_result_is_rebuilt_from_row_not_worker_state(env):  # noqa: F811
    """The whole AssessmentResult of a losing execution comes from the row:
    a flagged (canonical_from_row) finding must NOT read model/provider,
    retrieved or provenance from the loser's own graph state — otherwise M6
    attributes the winner's verdict to the loser's provider."""
    from app.pipeline.graph import _result_from_final

    session_factory, org_id = env
    _use(FakeLLM([_valid_draft()]))
    aid = create_assessment(session_factory, org_id, ["A.9.2"])
    winner = run_requirement(session_factory, aid, "A.9.2")
    db = session_factory()
    row = db.get(Finding, winner.finding_id)
    row_model, row_provider = row.final_model, row.final_provider
    row_retrieved_ids = [r["result_id"] for r in (row.retrieved or [])]
    db.close()

    # a loser's final_state: the finding dict was canonicalized + flagged by
    # _persist_finding, but the state still carries the loser's own model,
    # provider and evidence
    losing_state = {
        "finding": {
            "finding_id": winner.finding_id,
            "status": "VERIFIED",
            "verdict": "compliant",
            "canonical_from_row": True,
        },
        "final_model": "loser-model",
        "final_provider": "loser-provider",
        "retrieved": [{"result_id": "loser-evidence"}],
        "attempt_history": [{"attempt": 99}],
        "audit_log": [{"node": "loser"}],
    }
    result = _result_from_final(session_factory, losing_state, aid, "A.9.2")

    assert result.final_model == row_model
    assert result.final_provider == row_provider
    assert result.final_model != "loser-model"
    assert [r["result_id"] for r in result.retrieved] == row_retrieved_ids
    assert all(r["result_id"] != "loser-evidence" for r in result.retrieved)


def test_winner_result_still_comes_from_its_own_state(env):  # noqa: F811
    """The happy path is untouched: a winning execution (no canonical flag)
    still builds its result from graph state, preserving the richer per-call
    attempt_history the CLI prints."""
    from app.pipeline.graph import _result_from_final

    session_factory, org_id = env
    _use(FakeLLM([_valid_draft()]))
    aid = create_assessment(session_factory, org_id, ["A.9.2"])
    winning_state = {
        "finding": {"finding_id": "x", "status": "VERIFIED", "verdict": "compliant"},
        "final_model": "winner-model",
        "final_provider": "winner-provider",
        "retrieved": [{"result_id": "e1"}],
        "attempt_history": [{"attempt": 1, "calls": []}],
        "audit_log": [],
    }
    result = _result_from_final(session_factory, winning_state, aid, "A.9.2")
    assert result.final_model == "winner-model"
    assert result.final_provider == "winner-provider"
