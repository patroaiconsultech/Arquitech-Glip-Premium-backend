def _project(client,headers,name="Projeto"):
    r=client.post("/api/v1/projects",headers=headers,json={"name":name})
    assert r.status_code==201
    return r.json()

def _approved_draft(client,headers,project_id):
    d=client.post(
        f"/api/v1/projects/{project_id}/capabilities/draft-message",headers=headers,
        json={"channel":"whatsapp","recipient_role":"provider","intent":"follow_up",
              "instruction":"Solicitar retorno sobre iluminação.","source_refs":[]}
    ).json()
    assert client.post(
        f"/api/v1/projects/{project_id}/drafts/{d['draft_id']}/request-approval",headers=headers,
        json={"draft_version_id":d["draft_version_id"]}
    ).status_code==200
    a=client.post(
        f"/api/v1/projects/{project_id}/drafts/{d['draft_id']}/approve",headers=headers,
        json={"draft_version_id":d["draft_version_id"]}
    )
    assert a.status_code==200
    return d,a.json()

def test_budget_is_draft_and_tenant_scoped(client,auth_a,auth_b):
    p=_project(client,auth_a)
    b=client.post(f"/api/v1/projects/{p['id']}/budgets",headers=auth_a,json={"label":"Inicial","amount_cents":2500000})
    assert b.status_code==201
    assert b.json()["status"]=="draft"
    assert client.get(f"/api/v1/projects/{p['id']}/budgets",headers=auth_b).status_code==404

def test_approval_creates_immutable_approved_version_and_pending_memory_candidate(client,auth_a):
    p=_project(client,auth_a)
    _,approved=_approved_draft(client,auth_a,p["id"])
    assert approved["approved_version_id"]
    assert approved["memory_candidate_id"]
    versions=client.get(f"/api/v1/projects/{p['id']}/approved-versions",headers=auth_a).json()
    assert len(versions)==1
    candidates=client.get(f"/api/v1/projects/{p['id']}/memory/candidates",headers=auth_a).json()
    assert candidates[0]["status"]=="pending"
    assert client.get(f"/api/v1/projects/{p['id']}/memory",headers=auth_a).json()==[]

def test_memory_requires_explicit_human_promotion(client,auth_a):
    p=_project(client,auth_a)
    _,approved=_approved_draft(client,auth_a,p["id"])
    promoted=client.post(
        f"/api/v1/projects/{p['id']}/memory/candidates/{approved['memory_candidate_id']}/promote",
        headers=auth_a,json={"fact_key":"preferred_tone","fact_value":"elegante e objetiva"}
    )
    assert promoted.status_code==201
    memory=client.get(f"/api/v1/projects/{p['id']}/memory",headers=auth_a).json()
    assert len(memory)==1
    assert memory[0]["fact_key"]=="preferred_tone"

def test_project_knowledge_is_purpose_scoped(client,auth_a):
    p=_project(client,auth_a)
    k=client.post(
        f"/api/v1/projects/{p['id']}/knowledge",headers=auth_a,
        json={"knowledge_key":"lighting_decision","summary":"Luz quente aprovada no salão.",
              "source_ref":"decision:lighting:1","allowed_purposes":["draft_message"]}
    )
    assert k.status_code==201
    general=client.get(f"/api/v1/projects/{p['id']}/context?purpose=general",headers=auth_a).json()
    draft=client.get(f"/api/v1/projects/{p['id']}/context?purpose=draft_message",headers=auth_a).json()
    assert general["knowledge"]==[]
    assert len(draft["knowledge"])==1
    assert any(x.startswith("glip-knowledge:") for x in draft["source_refs"])

def test_approval_emits_outbox_event_but_no_delivery(client,auth_a):
    p=_project(client,auth_a)
    _approved_draft(client,auth_a,p["id"])
    outbox=client.get(f"/api/v1/projects/{p['id']}/outbox",headers=auth_a).json()
    assert len(outbox)==1
    assert outbox[0]["event_type"]=="project.draft.approved"
    # There is no public delivery endpoint in v0.5.
    assert client.post(f"/api/v1/projects/{p['id']}/send",headers=auth_a,json={}).status_code==404
