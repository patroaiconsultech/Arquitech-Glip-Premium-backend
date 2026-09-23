def test_project_creation_auto_creates_logical_cognitive_profile(client,auth_a):
    p=client.post("/api/v1/projects",headers=auth_a,json={"name":"Loja Jardins"}).json()
    r=client.get(f"/api/v1/projects/{p['id']}/cognitive-profile",headers=auth_a)
    assert r.status_code==200
    profile=r.json()
    assert profile["project_id"]==p["id"]
    assert profile["tenant_id"]=="tenant-a"
    assert profile["status"]=="active"
    assert profile["baseline_id"]=="glip.architecture.core"
    assert profile["memory_namespace"].startswith("glip:tenant-a:project:")
    assert "glip.draft_message.v1" in profile["enabled_capabilities"]

def test_project_cognitive_profile_is_tenant_scoped(client,auth_a,auth_b):
    p=client.post("/api/v1/projects",headers=auth_a,json={"name":"Loja A"}).json()
    r=client.get(f"/api/v1/projects/{p['id']}/cognitive-profile",headers=auth_b)
    assert r.status_code==404

def test_project_context_contains_only_project_profile(client,auth_a):
    p=client.post("/api/v1/projects",headers=auth_a,json={"name":"Projeto"}).json()
    ctx=client.get(f"/api/v1/projects/{p['id']}/context",headers=auth_a).json()
    assert ctx["cognitive_profile"]["memory_namespace"]==f"glip:tenant-a:project:{p['id']}"
