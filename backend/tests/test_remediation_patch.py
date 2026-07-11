"""M7b anchored-patch flow: drafting gates (raw-equality anchor, exactly one
occurrence), DRAFTING lease, human decision + token-fenced two-phase
activation, staleness pins, recovery, ABANDONED-does-not-reserve-content."""

import json

import pytest
from sqlalchemy import select

from app.models import (
    Chunk,
    Document,
    DocumentVersion,
    DocumentVersionEvent,
    PatchDecision,
    PatchProposal,
    RemediationAttempt,
    RemediationLlmCall,
)
from app.pipeline import llm as llm_service
from app.remediation import patcher as patcher_module
from tests.test_pipeline import DOC_TEXT, QUOTE
from tests.test_remediation_cases import (  # noqa: F401 — shared fixtures
    _create_case,
    _url,
    client,
    gap_env,
)
from tests.test_remediation_planner import (  # noqa: F401 — shared fixtures
    DynamicFake,
    _plan_json,
    _post_plan,
    approved_case,
)
from tests.test_remediation_actions import plan_case  # noqa: F401

ANCHOR = QUOTE  # verbatim, unique in DOC_TEXT, > 20 chars
NEW_TEXT = (
    "Les incidents impliquant un système d'IA sont enregistrés dans le registre "
    "dédié et revus mensuellement par le Comité IA."
)


def _patch_json(anchor=ANCHOR, page=1, operation="insert_after", new_text=NEW_TEXT, **extra) -> str:
    return json.dumps(
        {
            "anchor_quote": anchor,
            "anchor_page": page,
            "operation": operation,
            "new_text_fr": new_text,
            "rationale": "Couvre le critère de succès de l'action approuvée.",
            **extra,
        },
        ensure_ascii=False,
    )


@pytest.fixture()
def approved_action(client, plan_case):
    """plan_case + human approval of the action -> (org_id, case_id,
    action_id, doc_id). The org's TXT document is the patch target."""
    org_id, case_id, action_id = plan_case
    r = client.post(
        _url(org_id, case_id, f"/actions/{action_id}/review"),
        json={"action": "approve", "priority": "haute"},
    )
    assert r.status_code == 200
    docs = client.get(f"/api/organizations/{org_id}/documents").json()
    return org_id, case_id, action_id, docs[0]["id"]


def _post_proposal(client, org_id, case_id, action_id, doc_id, scripts):
    llm_service.set_provider(DynamicFake(scripts))
    return client.post(
        _url(org_id, case_id, f"/actions/{action_id}/patch-proposals"),
        json={"document_id": doc_id},
    )


def _decide(client, org_id, case_id, proposal_id, **body):
    return client.post(
        _url(org_id, case_id, f"/patch-proposals/{proposal_id}/decision"), json=body
    )


# ---------------------------------------------------------------- drafting


def test_verified_proposal_with_resolved_span(client, approved_action):
    org_id, case_id, action_id, doc_id = approved_action
    r = _post_proposal(client, org_id, case_id, action_id, doc_id, [_patch_json()])
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "VERIFIED"
    assert body["anchor_slice"] == ANCHOR  # server slice, not the model quote
    assert DOC_TEXT[body["anchor_char_start"]:body["anchor_char_end"]] == ANCHOR
    assert body["context_before"].endswith("utilisés.\n\n")
    assert body["requirement_ids"] == ["A.9.2"]  # human-approved effective scope
    # attempts + llm_calls provenance, stage 'patch'
    db = client.session_factory()
    attempts = db.scalars(
        select(RemediationAttempt).where(
            RemediationAttempt.patch_proposal_id == body["id"]
        )
    ).all()
    assert [a.stage for a in attempts] == ["patch"] and attempts[0].parsed_ok
    calls = db.scalars(
        select(RemediationLlmCall).where(
            RemediationLlmCall.remediation_attempt_id == attempts[0].id
        )
    ).all()
    assert len(calls) == 1 and calls[0].prompt_version == "patch-1"
    db.close()
    # the prompt served the full page text as a JSON-escaped block
    detail = client.get(_url(org_id, case_id)).json()
    assert any(e["event_type"] == "patch_proposed" for e in detail["events"])


def test_fabricated_anchor_repairs_then_abstains(client, approved_action):
    org_id, case_id, action_id, doc_id = approved_action
    bad = _patch_json(anchor="Cette phrase n'existe pas dans le document cible.")
    r = _post_proposal(client, org_id, case_id, action_id, doc_id, [bad, bad])
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "ABSTAINED"
    assert body["abstain_reason"] == "anchor_not_found"
    assert body["attempts"] == 2  # one bounded repair
    assert body["anchor_char_start"] is None and body["anchor_char_end"] is None


def test_normalization_level_near_anchor_is_rejected(client, approved_action):
    """The write gate is raw literal equality: an anchor differing only at
    normalization level (case fold) must fail — the read-side verifier would
    have accepted it."""
    org_id, case_id, action_id, doc_id = approved_action
    near = _patch_json(anchor=ANCHOR.lower())
    r = _post_proposal(client, org_id, case_id, action_id, doc_id, [near, near])
    assert r.json()["status"] == "ABSTAINED"
    assert r.json()["abstain_reason"] == "anchor_not_found"


def test_ambiguous_anchor_abstains_without_span(client, approved_action):
    org_id, case_id, action_id, _doc = approved_action
    dup_line = "La revue de conformité est réalisée chaque trimestre sans exception."
    dup_doc = f"Préambule.\n\n{dup_line}\n\nSection intermédiaire.\n\n{dup_line}\n"
    r = client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("doublons.txt", dup_doc.encode(), "text/plain")},
    )
    assert r.status_code == 201
    dup_id = r.json()["id"]
    bad = _patch_json(anchor=dup_line)
    r = _post_proposal(client, org_id, case_id, action_id, dup_id, [bad, bad])
    body = r.json()
    assert body["status"] == "ABSTAINED"
    assert body["abstain_reason"] == "anchor_ambiguous"
    assert body["anchor_char_start"] is None
    assert any("2 occurrences" in e for e in body["verifier_errors"])


def test_llm_supplied_context_fields_are_rejected(client, approved_action):
    """Adversarial: the model may not smuggle server-owned identifiers into
    the draft — extra fields fail the strict schema, then abstain."""
    org_id, case_id, action_id, doc_id = approved_action
    forged = _patch_json(document_version_id="forged-id", case_id="autre-cas")
    r = _post_proposal(client, org_id, case_id, action_id, doc_id, [forged, forged])
    body = r.json()
    assert body["status"] == "ABSTAINED" and body["abstain_reason"] == "schema_invalid"


def test_patch_requires_txt_md_target_and_approved_action(client, plan_case):
    org_id, case_id, action_id = plan_case
    docs = client.get(f"/api/organizations/{org_id}/documents").json()
    # action not yet APPROVED (PROPOSED)
    r = _post_proposal(client, org_id, case_id, action_id, docs[0]["id"], [_patch_json()])
    assert r.status_code == 409
    # approve, then target a PDF version: structurally refused before any LLM call
    client.post(
        _url(org_id, case_id, f"/actions/{action_id}/review"),
        json={"action": "approve", "priority": "haute"},
    )
    db = client.session_factory()
    doc = db.get(Document, docs[0]["id"])
    db.get(DocumentVersion, doc.current_version_id).canonical_format = "pdf"
    db.commit()
    r = _post_proposal(client, org_id, case_id, action_id, doc.id, [_patch_json()])
    assert r.status_code == 422
    assert "TXT/Markdown" in r.json()["detail"]
    db.get(DocumentVersion, doc.current_version_id).canonical_format = "txt"
    db.commit()
    db.close()


# ---------------------------------------------------------------- decision


def _verified_proposal(client, approved_action, **kw):
    org_id, case_id, action_id, doc_id = approved_action
    r = _post_proposal(client, org_id, case_id, action_id, doc_id, [_patch_json(**kw)])
    assert r.json()["status"] == "VERIFIED"
    return r.json()


def test_approve_activates_new_version(client, approved_action):
    org_id, case_id, _action_id, doc_id = approved_action
    proposal = _verified_proposal(client, approved_action)
    db = client.session_factory()
    base_vid = db.get(Document, doc_id).current_version_id

    r = _decide(client, org_id, case_id, proposal["id"], decision="approve")
    assert r.status_code == 200
    out = r.json()
    assert out["outcome"] == "activated"

    db.expire_all()
    doc = db.get(Document, doc_id)
    new = db.get(DocumentVersion, out["version_id"])
    base = db.get(DocumentVersion, base_vid)
    assert doc.current_version_id == new.id
    assert new.state == "ACTIVE" and new.origin == "patch"
    assert new.activation_token is None and new.version_number == 2
    assert base.state == "SUPERSEDED"
    assert doc.checksum == new.source_checksum  # mirror refreshed
    # the FINAL text was inserted right after the anchor
    page = new.pages[0].text
    assert ANCHOR + "\n\n" + NEW_TEXT in page
    # base pages/chunks survive (finding provenance)
    assert base.pages and db.scalars(
        select(Chunk.id).where(Chunk.document_version_id == base_vid)
    ).all()
    # document event stream: created -> indexed -> activated
    events = [
        e.event_type
        for e in db.scalars(
            select(DocumentVersionEvent)
            .where(DocumentVersionEvent.document_id == doc_id)
            .order_by(DocumentVersionEvent.sequence)
        )
    ]
    assert events[-3:] == ["version_created", "version_indexed", "version_activated"]
    db.close()
    # case event + retrieval serves ONLY the new content
    detail = client.get(_url(org_id, case_id)).json()
    assert any(e["event_type"] == "patch_approved" for e in detail["events"])
    r = client.post(
        f"/api/organizations/{org_id}/search",
        json={"query": "registre incidents IA revus mensuellement", "k": 4},
    )
    hit_versions = set()
    db = client.session_factory()
    for item in r.json():
        chunk = db.get(Chunk, item["result_id"])
        hit_versions.add(chunk.document_version_id)
    assert base_vid not in hit_versions
    db.close()

    # duplicate decision: idempotent status, never an opaque conflict
    r = _decide(client, org_id, case_id, proposal["id"], decision="approve")
    assert r.status_code == 200 and r.json()["outcome"] == "already_active"


def test_edit_applies_the_human_text_only(client, approved_action):
    org_id, case_id, _action_id, doc_id = approved_action
    proposal = _verified_proposal(client, approved_action, operation="replace")
    # edit without text is invalid
    assert _decide(client, org_id, case_id, proposal["id"], decision="edit").status_code == 422
    human = "Texte final rédigé par l'examinateur humain, appliqué tel quel."
    r = _decide(
        client, org_id, case_id, proposal["id"], decision="edit", final_text_fr=human
    )
    assert r.status_code == 200
    db = client.session_factory()
    new = db.get(DocumentVersion, r.json()["version_id"])
    page = new.pages[0].text
    assert human in page and NEW_TEXT not in page  # human text, not the AI draft
    assert ANCHOR not in page  # replace consumed the anchor span
    decision = db.scalar(select(PatchDecision))
    assert decision.decision == "edit" and decision.final_text_fr == human
    db.close()


def test_edit_preserves_exact_whitespace(client, approved_action):
    """The human's edited text is applied EXACTLY — leading/trailing (and
    internal) whitespace is preserved, not stripped (contract: 'appliquée
    telle quelle')."""
    org_id, case_id, _action_id, _doc = approved_action
    proposal = _verified_proposal(client, approved_action, operation="replace")
    # a whitespace-only edit is rejected BEFORE any decision is recorded, so
    # the proposal stays decidable
    r = _decide(client, org_id, case_id, proposal["id"], decision="edit", final_text_fr="   \n  ")
    assert r.status_code == 422
    # real text with significant leading/trailing whitespace is applied EXACTLY
    human = "  \tTexte avec espaces significatifs en début et fin.  \n"
    r = _decide(
        client, org_id, case_id, proposal["id"], decision="edit", final_text_fr=human
    )
    assert r.status_code == 200
    db = client.session_factory()
    new = db.get(DocumentVersion, r.json()["version_id"])
    assert human in new.pages[0].text  # exact bytes, untouched
    decision = db.scalar(select(PatchDecision))
    assert decision.final_text_fr == human
    db.close()


def test_reject_records_decision_without_version(client, approved_action):
    org_id, case_id, _action_id, _doc = approved_action
    proposal = _verified_proposal(client, approved_action)
    r = _decide(client, org_id, case_id, proposal["id"], decision="reject")
    assert r.status_code == 200 and r.json()["outcome"] == "rejected"
    db = client.session_factory()
    row = db.scalar(select(PatchDecision))
    assert row.result_version_id is None and row.final_text_fr is None
    assert db.scalar(select(DocumentVersion).where(DocumentVersion.origin == "patch")) is None
    db.close()
    detail = client.get(_url(org_id, case_id)).json()
    assert any(e["event_type"] == "patch_rejected" for e in detail["events"])


def test_action_rereview_between_proposal_and_decision_conflicts(client, approved_action):
    """Staleness pins (audit round 2 finding 11): a re-review bumps
    review_count, so the proposal's context no longer holds."""
    org_id, case_id, action_id, _doc = approved_action
    proposal = _verified_proposal(client, approved_action)
    r = client.post(
        _url(org_id, case_id, f"/actions/{action_id}/review"),
        json={"action": "approve", "priority": "normale"},
    )
    assert r.status_code == 200
    r = _decide(client, org_id, case_id, proposal["id"], decision="approve")
    assert r.status_code == 409
    assert "périmé" in r.json()["detail"]


def test_base_content_change_conflicts(client, approved_action):
    org_id, case_id, _action_id, doc_id = approved_action
    proposal = _verified_proposal(client, approved_action)
    db = client.session_factory()
    doc = db.get(Document, doc_id)
    db.get(DocumentVersion, doc.current_version_id).text_checksum = "drifted"
    db.commit()
    db.close()
    r = _decide(client, org_id, case_id, proposal["id"], decision="approve")
    assert r.status_code == 409
    assert "somme de contrôle" in r.json()["detail"]


def test_identical_resulting_content_conflicts(client, approved_action):
    """A replace whose final text equals the anchor reproduces the base
    content byte for byte: the per-document reversion rule refuses it."""
    org_id, case_id, _action_id, _doc = approved_action
    proposal = _verified_proposal(client, approved_action, operation="replace")
    r = _decide(
        client, org_id, case_id, proposal["id"], decision="edit", final_text_fr=ANCHOR
    )
    assert r.status_code == 409
    assert "Contenu identique" in r.json()["detail"]


# ------------------------------------------------- recovery + token fencing


def test_index_failure_then_recover_activates(client, approved_action, monkeypatch):
    org_id, case_id, _action_id, doc_id = approved_action
    proposal = _verified_proposal(client, approved_action)

    from app.services import qdrant as qdrant_service

    real_upsert = qdrant_service.upsert_points
    boom = {"armed": True}

    def failing_upsert(points):
        if boom["armed"]:
            boom["armed"] = False
            raise ConnectionError("qdrant down")
        return real_upsert(points)

    monkeypatch.setattr(patcher_module.qdrant, "upsert_points", failing_upsert)
    r = _decide(client, org_id, case_id, proposal["id"], decision="approve")
    assert r.status_code == 503
    body = r.json()
    assert body["outcome"] == "index_failed"
    db = client.session_factory()
    cand = db.get(DocumentVersion, body["version_id"])
    assert cand.state == "INDEX_FAILED" and cand.activation_error
    assert db.get(Document, doc_id).current_version_id != cand.id  # base still current
    db.close()

    # duplicate decision now reports the pending candidate (202), not a 409
    r = _decide(client, org_id, case_id, proposal["id"], decision="approve")
    assert r.status_code == 202 and r.json()["outcome"] == "pending"

    # recovery re-drives idempotently to ACTIVE
    r = client.post(
        _url(org_id, case_id, f"/patch-proposals/{proposal['id']}/recover"), json={}
    )
    assert r.status_code == 200 and r.json()["outcome"] == "activated"
    db = client.session_factory()
    db.expire_all()
    assert db.get(Document, doc_id).current_version_id == body["version_id"]
    events = [
        e.event_type
        for e in db.scalars(
            select(DocumentVersionEvent)
            .where(DocumentVersionEvent.document_id == doc_id)
            .order_by(DocumentVersionEvent.sequence)
        )
    ]
    assert "version_index_failed" in events and "version_recovered" in events
    db.close()
    # recover after success is an idempotent 200
    r = client.post(
        _url(org_id, case_id, f"/patch-proposals/{proposal['id']}/recover"), json={}
    )
    assert r.status_code == 200 and r.json()["outcome"] == "already_active"


def test_assessment_conflict_keeps_candidate_recoverable(client, approved_action, monkeypatch):
    """An assessment starting between Tx A and Tx B: temporary conflict —
    PENDING_INDEX kept, token cleared, immediately recoverable (no fake
    stale-lease wait)."""
    org_id, case_id, _action_id, doc_id = approved_action
    proposal = _verified_proposal(client, approved_action)

    real = patcher_module.running_assessment_id
    sequence = {"calls": 0}

    def racing(db, oid):
        sequence["calls"] += 1
        # call 1 = Tx A gate (clear), call 2 = Tx B gate (assessment started)
        return None if sequence["calls"] == 1 else (
            "fake-assessment" if sequence["calls"] == 2 else None
        )

    monkeypatch.setattr(patcher_module, "running_assessment_id", racing)
    r = _decide(client, org_id, case_id, proposal["id"], decision="approve")
    assert r.status_code == 409
    body = r.json()
    assert body["outcome"] == "assessment_conflict"
    db = client.session_factory()
    cand = db.get(DocumentVersion, body["version_id"])
    assert cand.state == "PENDING_INDEX"
    assert cand.activation_token is None  # cleared: recoverable NOW
    assert cand.activation_error == "assessment_conflict"
    db.close()

    r = client.post(
        _url(org_id, case_id, f"/patch-proposals/{proposal['id']}/recover"), json={}
    )
    assert r.status_code == 200 and r.json()["outcome"] == "activated"


def test_stale_branch_abandoned_and_does_not_reserve_content(client, approved_action, monkeypatch):
    """Two candidates over one base: the second to activate wins nothing —
    the stale branch lands terminal ABANDONED(stale_base) and its
    text_checksum is NOT reserved: a fresh authorized proposal recreating the
    same content succeeds."""
    org_id, case_id, action_id, doc_id = approved_action

    # candidate 1 strands at INDEX_FAILED (its content: insert NEW_TEXT)
    proposal1 = _verified_proposal(client, approved_action)
    from app.services import qdrant as qdrant_service

    real_upsert = qdrant_service.upsert_points
    boom = {"armed": True}

    def failing_upsert(points):
        if boom["armed"]:
            boom["armed"] = False
            raise ConnectionError("qdrant down")
        return real_upsert(points)

    monkeypatch.setattr(patcher_module.qdrant, "upsert_points", failing_upsert)
    r = _decide(client, org_id, case_id, proposal1["id"], decision="approve")
    assert r.json()["outcome"] == "index_failed"
    stale_vid = r.json()["version_id"]

    # candidate 2 (different content) activates and supersedes the base
    annual = "Une revue annuelle des incidents est ajoutée au programme d'audit."
    proposal2 = _verified_proposal(client, approved_action, new_text=annual)
    r = _decide(client, org_id, case_id, proposal2["id"], decision="approve")
    assert r.json()["outcome"] == "activated"

    # recovering candidate 1 now fails its CAS -> terminal ABANDONED(stale_base)
    r = client.post(
        _url(org_id, case_id, f"/patch-proposals/{proposal1['id']}/recover"), json={}
    )
    assert r.status_code == 409
    assert r.json()["outcome"] == "abandoned:stale_base"
    db = client.session_factory()
    stale = db.get(DocumentVersion, stale_vid)
    assert stale.state == "ABANDONED" and stale.abandoned_reason == "stale_base"
    db.close()
    # terminal: recover refuses
    r = client.post(
        _url(org_id, case_id, f"/patch-proposals/{proposal1['id']}/recover"), json={}
    )
    assert r.status_code == 409 and r.json()["outcome"] == "abandoned:stale_base"

    # a FRESH proposal producing candidate 1's EXACT content succeeds: the
    # abandoned twin does not reserve its text_checksum. Replacing candidate
    # 2's inserted sentence with candidate 1's text reproduces candidate 1's
    # page byte for byte (same insertion point, same surrounding base text).
    proposal3 = _verified_proposal(
        client, approved_action, anchor=annual, operation="replace"
    )
    r = _decide(client, org_id, case_id, proposal3["id"], decision="approve")
    assert r.json()["outcome"] == "activated"
    db = client.session_factory()
    new = db.get(DocumentVersion, r.json()["version_id"])
    assert new.text_checksum == stale.text_checksum  # same content, new lineage
    db.close()


def test_drafting_lease_blocks_then_recovers(client, approved_action):
    """A live DRAFTING proposal blocks a second draft; once its heartbeat is
    stale it is recovered to terminal ABSTAINED(draft_interrupted)."""
    from datetime import datetime, timedelta, timezone

    org_id, case_id, action_id, doc_id = approved_action
    db = client.session_factory()
    from app.remediation.patcher import action_context
    from app.remediation.service import lock_case

    case = lock_case(db, org_id, case_id)
    from app.models import RemediationAction

    action = db.get(RemediationAction, action_id)
    ctx = action_context(db, case, action)
    doc = db.get(Document, doc_id)
    stuck = PatchProposal(
        case_id=case_id,
        action_id=action_id,
        document_id=doc_id,
        document_version_id=doc.current_version_id,
        base_text_checksum="x",
        requirement_ids=[],
        requirements_snapshot=[],
        status="DRAFTING",
        drafting_token="tok",
        drafting_started_at=datetime.now(timezone.utc),
        drafting_heartbeat_at=datetime.now(timezone.utc),
        prompt_version="patch-1",
        **ctx["pins"],
    )
    db.add(stuck)
    db.commit()

    r = _post_proposal(client, org_id, case_id, action_id, doc_id, [_patch_json()])
    assert r.status_code == 409  # live lease blocks

    db.execute(
        PatchProposal.__table__.update()
        .where(PatchProposal.id == stuck.id)
        .values(drafting_heartbeat_at=datetime.now(timezone.utc) - timedelta(seconds=900))
    )
    db.commit()
    r = _post_proposal(client, org_id, case_id, action_id, doc_id, [_patch_json()])
    assert r.status_code == 201 and r.json()["status"] == "VERIFIED"
    db.expire_all()
    recovered = db.get(PatchProposal, stuck.id)
    assert recovered.status == "ABSTAINED"
    assert recovered.abstain_reason == "draft_interrupted"
    db.close()
