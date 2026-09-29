from uuid import uuid4

from sqlalchemy import select

from glip.models import Membership, Project, ProjectAuditEvent, ProjectCreateIdempotency


def _headers(base:dict,key:str|None=None):
    out=dict(base)
    out["Idempotency-Key"]=key or str(uuid4())
    return out


def _membership(db,tenant_id:str,subject:str,role:str):
    db.add(Membership(
        tenant_id=tenant_id,
        external_subject=subject,
        display_name=subject,
        role=role,
        active=True,
    ))
    db.commit()
    return {"X-GLIP-Tenant-ID":tenant_id,"X-GLIP-User-ID":subject}


def test_project_create_requires_idempotency_header(client,auth_a):
    r=client.request(
        "POST",
        "/api/v1/projects",
        headers=auth_a,
        json={"name":"Sem chave"},
    )
    assert r.status_code==422


def test_project_create_replays_same_result_for_same_key_and_body(client,auth_a,db):
    key="f01-create-1"
    h=_headers(auth_a,key)
    first=client.post("/api/v1/projects",headers=h,json={"name":"Babilonia"})
    second=client.post("/api/v1/projects",headers=h,json={"name":"Babilonia"})
    assert first.status_code==201
    assert second.status_code==201
    assert second.headers["Idempotent-Replay"]=="true"
    assert first.json()["id"]==second.json()["id"]

    projects=db.scalars(select(Project).where(
        Project.tenant_id=="tenant-a",
        Project.name=="Babilonia",
    )).all()
    assert len(projects)==1

    idem=db.scalars(select(ProjectCreateIdempotency).where(
        ProjectCreateIdempotency.tenant_id=="tenant-a",
        ProjectCreateIdempotency.idempotency_key==key,
    )).all()
    assert len(idem)==1

    events=db.scalars(select(ProjectAuditEvent).where(
        ProjectAuditEvent.tenant_id=="tenant-a",
        ProjectAuditEvent.project_id==first.json()["id"],
        ProjectAuditEvent.event_type=="project.created",
    )).all()
    assert len(events)==1


def test_project_create_rejects_key_reuse_with_different_payload(client,auth_a):
    h=_headers(auth_a,"f01-create-conflict")
    assert client.post(
        "/api/v1/projects",
        headers=h,
        json={"name":"Projeto A"},
    ).status_code==201

    r=client.post(
        "/api/v1/projects",
        headers=h,
        json={"name":"Projeto B"},
    )
    assert r.status_code==409
    assert r.json()["detail"]=="idempotency_key_reused"


def test_idempotency_is_tenant_scoped(client,auth_a,auth_b):
    key="same-key-different-tenants"
    a=client.post(
        "/api/v1/projects",
        headers=_headers(auth_a,key),
        json={"name":"A"},
    )
    b=client.post(
        "/api/v1/projects",
        headers=_headers(auth_b,key),
        json={"name":"B"},
    )
    assert a.status_code==201
    assert b.status_code==201
    assert a.json()["id"]!=b.json()["id"]


def test_member_can_create_and_update_but_cannot_archive(client,auth_a,db):
    member=_membership(db,"tenant-a","member-a","member")
    created=client.post(
        "/api/v1/projects",
        headers=_headers(member),
        json={"name":"Projeto"},
    ).json()

    updated=client.patch(
        f"/api/v1/projects/{created['id']}",
        headers=member,
        json={"name":"Projeto atualizado","description":"Descrição"},
    )
    assert updated.status_code==200
    assert updated.json()["name"]=="Projeto atualizado"

    denied=client.post(
        f"/api/v1/projects/{created['id']}/archive",
        headers=member,
    )
    assert denied.status_code==403
    assert denied.json()["detail"]=="capability_required"


def test_unknown_role_cannot_mutate_projects(client,auth_a,db):
    external=_membership(db,"tenant-a","client-a","client")
    denied=client.post(
        "/api/v1/projects",
        headers=_headers(external),
        json={"name":"Não permitido"},
    )
    assert denied.status_code==403
    assert denied.json()["detail"]=="capability_required"


def test_owner_can_edit_archive_list_restore_and_audit(client,auth_a,db):
    created=client.post(
        "/api/v1/projects",
        headers=_headers(auth_a),
        json={"name":"Projeto","description":"Inicial"},
    ).json()
    pid=created["id"]

    updated=client.patch(
        f"/api/v1/projects/{pid}",
        headers=auth_a,
        json={
            "name":"Projeto Premium",
            "description":"Atualizada",
            "status":"active",
        },
    )
    assert updated.status_code==200
    assert updated.json()["context_version"]==created["context_version"]+1

    archived=client.post(f"/api/v1/projects/{pid}/archive",headers=auth_a)
    assert archived.status_code==200
    assert archived.json()["archived_at"] is not None

    active_ids={
        p["id"] for p in client.get("/api/v1/projects",headers=auth_a).json()
    }
    archived_ids={
        p["id"]
        for p in client.get("/api/v1/projects?archived=true",headers=auth_a).json()
    }
    assert pid not in active_ids
    assert pid in archived_ids

    blocked=client.patch(
        f"/api/v1/projects/{pid}",
        headers=auth_a,
        json={"name":"Bloqueado"},
    )
    assert blocked.status_code==409
    assert blocked.json()["detail"]=="project_archived"

    restored=client.post(f"/api/v1/projects/{pid}/restore",headers=auth_a)
    assert restored.status_code==200
    assert restored.json()["archived_at"] is None
    assert pid in {
        p["id"] for p in client.get("/api/v1/projects",headers=auth_a).json()
    }

    event_types={
        e.event_type
        for e in db.scalars(select(ProjectAuditEvent).where(
            ProjectAuditEvent.tenant_id=="tenant-a",
            ProjectAuditEvent.project_id==pid,
        )).all()
    }
    assert {
        "project.created",
        "project.updated",
        "project.archived",
        "project.restored",
    }<=event_types


def test_cross_tenant_mutations_are_hidden(client,auth_a,auth_b):
    created=client.post(
        "/api/v1/projects",
        headers=_headers(auth_a),
        json={"name":"Tenant A"},
    ).json()
    pid=created["id"]

    assert client.patch(
        f"/api/v1/projects/{pid}",
        headers=auth_b,
        json={"name":"X"},
    ).status_code==404
    assert client.post(
        f"/api/v1/projects/{pid}/archive",
        headers=auth_b,
    ).status_code==404
    assert client.post(
        f"/api/v1/projects/{pid}/restore",
        headers=auth_b,
    ).status_code==404


def test_me_exposes_effective_project_capabilities(client,auth_a,db):
    owner=client.get("/api/v1/me",headers=auth_a).json()
    assert "project.archive" in owner["capabilities"]

    member=_membership(db,"tenant-a","member-cap","member")
    member_me=client.get("/api/v1/me",headers=member).json()
    assert "project.update" in member_me["capabilities"]
    assert "project.archive" not in member_me["capabilities"]
