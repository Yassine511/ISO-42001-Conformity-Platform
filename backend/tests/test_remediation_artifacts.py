"""M7b PDF/DOCX artifact flow + superseding upload lineage + deletion guards.

The artifact drafter produces ONLY a labelled Markdown proposal (never a
version). A new PDF/DOCX version comes solely from an explicit human
superseding re-upload, which may cite the artifact to close the
corrective-action loop.
"""

import io
import json

import pytest
from docx import Document as DocxDocument
from sqlalchemy import select

from app.models import (
    Document,
    DocumentVersion,
    DocumentVersionEvent,
    RemediationArtifact,
)
from app.pipeline import llm as llm_service
from tests.test_remediation_cases import _url, client  # noqa: F401
from tests.test_remediation_patch import (  # noqa: F401 — shared fixtures
    approved_action,
    approved_case,
    client,
    gap_env,
    plan_case,
)
from tests.test_remediation_planner import DynamicFake


def _docx_bytes(text: str) -> bytes:
    d = DocxDocument()
    d.add_paragraph(text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _artifact_json(content="## Révision proposée\n\nNouveau paragraphe de politique.") -> str:
    return json.dumps(
        {"content_md": content, "rationale": "Couvre l'action approuvée."},
        ensure_ascii=False,
    )


@pytest.fixture()
def docx_action(client, plan_case):
    """approved action + a DOCX document target -> (org_id, case_id,
    action_id, doc_id)."""
    org_id, case_id, action_id = plan_case
    r = client.post(
        _url(org_id, case_id, f"/actions/{action_id}/review"),
        json={"action": "approve", "priority": "haute"},
    )
    assert r.status_code == 200
    r = client.post(
        f"/api/organizations/{org_id}/documents",
        files={
            "file": (
                "politique.docx",
                _docx_bytes("Politique documentaire initiale sur l'IA."),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert r.status_code == 201
    return org_id, case_id, action_id, r.json()["id"]


def _post_artifact(client, org_id, case_id, action_id, doc_id, scripts):
    llm_service.set_provider(DynamicFake(scripts))
    return client.post(
        _url(org_id, case_id, f"/actions/{action_id}/artifacts"),
        json={"document_id": doc_id},
    )


# --------------------------------------------------------------- artifacts


def test_artifact_created_for_docx_target(client, docx_action):
    org_id, case_id, action_id, doc_id = docx_action
    r = _post_artifact(client, org_id, case_id, action_id, doc_id, [_artifact_json()])
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "VERIFIED"
    assert body["canonical_format"] == "docx"
    assert body["filename"].endswith(".md")
    # download carries the labelled header + content
    r = client.get(
        _url(org_id, case_id, f"/artifacts/{body['id']}/download")
    )
    assert r.status_code == 200
    text = r.content.decode("utf-8")
    assert "brouillon IA" in text and "Nouveau paragraphe" in text
    # attempts logged under stage 'artifact'
    db = client.session_factory()
    from app.models import RemediationAttempt

    attempts = db.scalars(
        select(RemediationAttempt).where(
            RemediationAttempt.remediation_artifact_id == body["id"]
        )
    ).all()
    assert [a.stage for a in attempts] == ["artifact"]
    db.close()
    detail = client.get(_url(org_id, case_id)).json()
    assert any(e["event_type"] == "artifact_created" for e in detail["events"])


def test_artifact_llm_failure_abstains_with_logging(client, docx_action):
    org_id, case_id, action_id, doc_id = docx_action
    r = _post_artifact(client, org_id, case_id, action_id, doc_id, [None, None])
    body = r.json()
    assert body["status"] == "ABSTAINED"
    assert body["abstain_reason"] in ("llm_error", "rate_limited")
    db = client.session_factory()
    from app.models import RemediationAttempt, RemediationLlmCall

    attempts = db.scalars(
        select(RemediationAttempt).where(
            RemediationAttempt.remediation_artifact_id == body["id"]
        )
    ).all()
    assert attempts and all(not a.parsed_ok for a in attempts)
    assert db.scalars(select(RemediationLlmCall)).first() is not None
    db.close()


def test_artifact_rejects_txt_target(client, approved_action):
    """The artifact flow is PDF/DOCX only; a TXT target belongs to the patch
    flow."""
    org_id, case_id, action_id, txt_doc = approved_action
    r = _post_artifact(client, org_id, case_id, action_id, txt_doc, [_artifact_json()])
    assert r.status_code == 422


def test_patch_flow_never_creates_pdf_docx_version(client, docx_action):
    """The anchored-patch endpoint refuses a DOCX target: only a human
    superseding upload can version a PDF/DOCX."""
    org_id, case_id, action_id, doc_id = docx_action
    llm_service.set_provider(DynamicFake([]))
    r = client.post(
        _url(org_id, case_id, f"/actions/{action_id}/patch-proposals"),
        json={"document_id": doc_id},
    )
    assert r.status_code == 422
    assert "TXT/Markdown" in r.json()["detail"]
    # no version was created
    db = client.session_factory()
    versions = db.scalars(
        select(DocumentVersion).where(DocumentVersion.document_id == doc_id)
    ).all()
    assert len(versions) == 1  # only the original upload version
    db.close()


# ------------------------------------------------- superseding uploads


def test_supersede_upload_with_lineage(client, docx_action):
    """A verified artifact -> human uploads the revised DOCX with
    remediation_artifact_id: new version ACTIVE, old SUPERSEDED, both event
    streams, lineage recorded on the version."""
    org_id, case_id, action_id, doc_id = docx_action
    artifact = _post_artifact(
        client, org_id, case_id, action_id, doc_id, [_artifact_json()]
    ).json()
    db = client.session_factory()
    base_vid = db.get(Document, doc_id).current_version_id
    db.close()

    r = client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("politique.docx", _docx_bytes("Politique révisée par un humain."), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={
            "supersedes_version_id": base_vid,
            "remediation_artifact_id": artifact["id"],
        },
    )
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["outcome"] == "activated"

    db = client.session_factory()
    doc = db.get(Document, doc_id)
    new = db.get(DocumentVersion, out["version_id"])
    base = db.get(DocumentVersion, base_vid)
    assert doc.current_version_id == new.id
    assert new.state == "ACTIVE" and new.origin == "upload"
    assert new.source_artifact_id == artifact["id"]  # lineage recorded
    assert new.version_number == 2 and base.state == "SUPERSEDED"
    # both event streams
    vevents = [
        e.event_type
        for e in db.scalars(
            select(DocumentVersionEvent)
            .where(DocumentVersionEvent.document_id == doc_id)
            .order_by(DocumentVersionEvent.sequence)
        )
    ]
    assert "version_superseded_by_upload" in vevents
    db.close()
    detail = client.get(_url(org_id, case_id)).json()
    assert any(
        e["event_type"] == "version_superseded_by_upload" for e in detail["events"]
    )


def test_supersede_wrong_family_rejected(client, docx_action):
    org_id, case_id, action_id, doc_id = docx_action
    db = client.session_factory()
    base_vid = db.get(Document, doc_id).current_version_id
    db.close()
    # uploading a TXT to supersede a DOCX crosses format families
    r = client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("politique.txt", b"Texte de remplacement.", "text/plain")},
        data={"supersedes_version_id": base_vid},
    )
    assert r.status_code == 422
    assert "format incompatible" in r.json()["detail"]


def test_supersede_artifact_targeting_other_version_rejected(client, docx_action):
    """An artifact drafted against version A cannot back a supersession of a
    different base version."""
    org_id, case_id, action_id, doc_id = docx_action
    artifact = _post_artifact(
        client, org_id, case_id, action_id, doc_id, [_artifact_json()]
    ).json()
    # activate one plain supersession first so a version B exists
    db = client.session_factory()
    base_vid = db.get(Document, doc_id).current_version_id
    db.close()
    r = client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("politique.docx", _docx_bytes("Version B intermédiaire."), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"supersedes_version_id": base_vid},
    )
    assert r.status_code == 201 and r.json()["outcome"] == "activated"
    new_vid = r.json()["version_id"]
    # now the artifact (targeting version A) cannot supersede version B
    r = client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("politique.docx", _docx_bytes("Tentative avec artefact périmé."), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"supersedes_version_id": new_vid, "remediation_artifact_id": artifact["id"]},
    )
    assert r.status_code == 409
    assert "autorité" in r.json()["detail"]


def test_supersede_plain_upload_no_lineage(client, docx_action):
    """A superseding upload WITHOUT an artifact id: still versions the
    document, but source_artifact_id stays NULL and no case event fires."""
    org_id, case_id, action_id, doc_id = docx_action
    db = client.session_factory()
    base_vid = db.get(Document, doc_id).current_version_id
    db.close()
    r = client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("politique.docx", _docx_bytes("Révision manuelle sans artefact."), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"supersedes_version_id": base_vid},
    )
    assert r.status_code == 201 and r.json()["outcome"] == "activated"
    db = client.session_factory()
    new = db.get(DocumentVersion, r.json()["version_id"])
    assert new.source_artifact_id is None
    db.close()


def test_supersede_upload_retry_is_idempotent(client, docx_action):
    """A client that timed out after a successful superseding upload resubmits
    the identical request: the second call returns already_active (200), not a
    stale-base 409 (rev.6 timeout/lost-response recovery contract)."""
    org_id, case_id, action_id, doc_id = docx_action
    artifact = _post_artifact(
        client, org_id, case_id, action_id, doc_id, [_artifact_json()]
    ).json()
    db = client.session_factory()
    base_vid = db.get(Document, doc_id).current_version_id
    db.close()

    def _upload():
        return client.post(
            f"/api/organizations/{org_id}/documents",
            files={"file": ("politique.docx", _docx_bytes("Contenu révisé idempotent."), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
            data={"supersedes_version_id": base_vid, "remediation_artifact_id": artifact["id"]},
        )

    r1 = _upload()
    assert r1.status_code == 201 and r1.json()["outcome"] == "activated"
    v2 = r1.json()["version_id"]
    # identical retry against the now-SUPERSEDED base -> idempotent success
    r2 = _upload()
    assert r2.status_code == 200, r2.text
    assert r2.json()["outcome"] == "already_active"
    assert r2.json()["version_id"] == v2
    # no third version was created
    db = client.session_factory()
    versions = db.scalars(
        select(DocumentVersion).where(DocumentVersion.document_id == doc_id)
    ).all()
    assert len(versions) == 2
    db.close()


def test_supersede_ignores_forged_mime(client, docx_action):
    """canonical_format is derived from the extension, never the client
    content_type: a .docx uploaded with a forged text/plain MIME is still
    treated as docx and supersedes the docx base."""
    org_id, case_id, action_id, doc_id = docx_action
    db = client.session_factory()
    base_vid = db.get(Document, doc_id).current_version_id
    db.close()
    r = client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("politique.docx", _docx_bytes("Révision avec MIME falsifié."), "text/plain")},
        data={"supersedes_version_id": base_vid},
    )
    assert r.status_code == 201 and r.json()["outcome"] == "activated"
    db = client.session_factory()
    new = db.get(DocumentVersion, r.json()["version_id"])
    assert new.canonical_format == "docx"  # extension wins, not the forged MIME
    db.close()


def test_artifact_reads_enforce_tenant(client, docx_action):
    """An artifact from org A must not be readable through an org-B URL even
    with A's case/artifact ids (tenant-ownership guard on the M7b routes)."""
    org_a, case_id, action_id, doc_id = docx_action
    art = _post_artifact(client, org_a, case_id, action_id, doc_id, [_artifact_json()]).json()
    org_b = client.post("/api/organizations", json={"name": "Autre locataire"}).json()["id"]

    # list through the wrong org -> 404 (case not in org B)
    r = client.get(
        f"/api/organizations/{org_b}/remediation-cases/{case_id}/actions/{action_id}/artifacts"
    )
    assert r.status_code == 404
    # download through the wrong org -> 404
    r = client.get(
        f"/api/organizations/{org_b}/remediation-cases/{case_id}/artifacts/{art['id']}/download"
    )
    assert r.status_code == 404
    # the legitimate org still works
    r = client.get(
        f"/api/organizations/{org_a}/remediation-cases/{case_id}/artifacts/{art['id']}/download"
    )
    assert r.status_code == 200


# --------------------------------------------------------------- deletion


def test_delete_refused_with_version_history(client, docx_action):
    org_id, case_id, action_id, doc_id = docx_action
    db = client.session_factory()
    base_vid = db.get(Document, doc_id).current_version_id
    db.close()
    client.post(
        f"/api/organizations/{org_id}/documents",
        files={"file": ("politique.docx", _docx_bytes("Nouvelle révision."), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")},
        data={"supersedes_version_id": base_vid},
    )
    r = client.delete(f"/api/documents/{doc_id}")
    assert r.status_code == 409
    assert "historique de versions" in r.json()["detail"]


def test_delete_refused_with_artifact_lineage(client, docx_action):
    org_id, case_id, action_id, doc_id = docx_action
    _post_artifact(client, org_id, case_id, action_id, doc_id, [_artifact_json()])
    r = client.delete(f"/api/documents/{doc_id}")
    assert r.status_code == 409
    assert "remédiation" in r.json()["detail"]
