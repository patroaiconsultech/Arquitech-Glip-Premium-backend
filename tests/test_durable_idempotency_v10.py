import json
from sqlalchemy import select

from glip.models import IntegrationExecution, Draft, DraftVersion

def payload(instruction="Solicitar confirmação."):
    return {
        "channel":"whatsapp",
        "recipient_role":"provider",
        "intent":"follow_up",
        "instruction":instruction,
        "source_refs":[],
    }

def test_same_request_id_replays_same_domain_result_without_duplicate_draft(client,db,auth_a):
    project=client.post("/api/v1/projects",headers=auth_a,json={"name":"Projeto"}).json()
    headers={**auth_a,"X-Request-ID":"same-request-0001","X-Correlation-ID":"corr-0001"}

    first=client.post(
        f"/api/v1/projects/{project['id']}/capabilities/draft-message",
        headers=headers,json=payload(),
    )
    second=client.post(
        f"/api/v1/projects/{project['id']}/capabilities/draft-message",
        headers=headers,json=payload(),
    )
    assert first.status_code==200
    assert second.status_code==200
    assert second.json()==first.json()

    integrations=db.scalars(select(IntegrationExecution).where(
        IntegrationExecution.tenant_id=="tenant-a",
        IntegrationExecution.request_id=="same-request-0001",
    )).all()
    drafts=db.scalars(select(Draft).where(
        Draft.tenant_id=="tenant-a",
        Draft.project_id==project["id"],
    )).all()
    versions=db.scalars(select(DraftVersion).where(
        DraftVersion.tenant_id=="tenant-a",
        DraftVersion.project_id==project["id"],
    )).all()
    assert len(integrations)==1
    assert len(drafts)==1
    assert len(versions)==1
    assert integrations[0].status=="completed"
    assert integrations[0].domain_response_json==first.json()
    assert integrations[0].request_json["schema_version"]=="ORKIO-CAPABILITY-REQUEST-1"

def test_same_request_id_with_changed_body_is_conflict(client,db,auth_a):
    project=client.post("/api/v1/projects",headers=auth_a,json={"name":"Projeto"}).json()
    headers={**auth_a,"X-Request-ID":"same-request-0002","X-Correlation-ID":"corr-0002"}
    first=client.post(
        f"/api/v1/projects/{project['id']}/capabilities/draft-message",
        headers=headers,json=payload("Mensagem A"),
    )
    assert first.status_code==200
    changed=client.post(
        f"/api/v1/projects/{project['id']}/capabilities/draft-message",
        headers=headers,json=payload("Mensagem B"),
    )
    assert changed.status_code==409
    assert changed.json()["detail"]=="idempotency_key_reused_with_different_request"

def test_idempotency_is_tenant_scoped(client,db,auth_a,auth_b):
    pa=client.post("/api/v1/projects",headers=auth_a,json={"name":"A"}).json()
    pb=client.post("/api/v1/projects",headers=auth_b,json={"name":"B"}).json()
    ha={**auth_a,"X-Request-ID":"shared-request-1","X-Correlation-ID":"ca-000001"}
    hb={**auth_b,"X-Request-ID":"shared-request-1","X-Correlation-ID":"cb-000001"}
    assert client.post(
        f"/api/v1/projects/{pa['id']}/capabilities/draft-message",headers=ha,json=payload()
    ).status_code==200
    assert client.post(
        f"/api/v1/projects/{pb['id']}/capabilities/draft-message",headers=hb,json=payload()
    ).status_code==200
    rows=db.scalars(select(IntegrationExecution).where(
        IntegrationExecution.request_id=="shared-request-1"
    )).all()
    assert {x.tenant_id for x in rows}=={"tenant-a","tenant-b"}

def test_canonical_request_does_not_persist_full_project_context(client,db,auth_a):
    project=client.post("/api/v1/projects",headers=auth_a,json={"name":"Projeto Sensível"}).json()
    headers={**auth_a,"X-Request-ID":"minimal-context-1","X-Correlation-ID":"corr-minimal-1"}
    r=client.post(
        f"/api/v1/projects/{project['id']}/capabilities/draft-message",
        headers=headers,json=payload(),
    )
    assert r.status_code==200
    row=db.scalar(select(IntegrationExecution).where(
        IntegrationExecution.request_id=="minimal-context-1"
    ))
    raw=json.dumps(row.request_json,ensure_ascii=False)
    assert "Projeto Sensível" not in raw
    assert "storage_ref" not in raw
    assert "authorized_sources" not in raw
