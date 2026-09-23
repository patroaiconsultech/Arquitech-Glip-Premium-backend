def test_tenant_isolation(client,auth_a,auth_b):
    p=client.post("/api/v1/projects",headers=auth_a,json={"name":"Projeto A"}).json()
    assert client.get(f"/api/v1/projects/{p['id']}",headers=auth_b).status_code==404

def test_draft_never_external_write(client,auth_a):
    p=client.post("/api/v1/projects",headers=auth_a,json={"name":"Projeto"}).json()
    d=client.post(f"/api/v1/projects/{p['id']}/capabilities/draft-message",headers=auth_a,
      json={"channel":"whatsapp","recipient_role":"provider","intent":"follow_up","instruction":"Solicitar retorno.","voice_profile_id":"glip.voice.sabrina.v1","source_refs":[]})
    assert d.status_code==200
    assert d.json()["external_write_allowed"] is False
    assert d.json()["approval_required"] is True

def test_edit_invalidates_old_approval(client,auth_a):
    p=client.post("/api/v1/projects",headers=auth_a,json={"name":"Projeto"}).json()
    d=client.post(f"/api/v1/projects/{p['id']}/capabilities/draft-message",headers=auth_a,
      json={"instruction":"Cobrar retorno.","source_refs":[]}).json()
    assert client.post(f"/api/v1/projects/{p['id']}/drafts/{d['draft_id']}/request-approval",headers=auth_a,
      json={"draft_version_id":d["draft_version_id"]}).status_code==200
    v=client.post(f"/api/v1/projects/{p['id']}/drafts/{d['draft_id']}/versions",headers=auth_a,json={"content":"Nova versão"}).json()
    old=client.post(f"/api/v1/projects/{p['id']}/drafts/{d['draft_id']}/approve",headers=auth_a,json={"draft_version_id":d["draft_version_id"]})
    assert old.status_code in (404,409)
    assert v["version"]==2
