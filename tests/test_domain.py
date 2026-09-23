def test_provider_is_tenant_scoped(client,auth_a,auth_b):
    x=client.post("/api/v1/providers",headers=auth_a,json={"name":"Luz Premium"}).json()
    providers_b=client.get("/api/v1/providers",headers=auth_b).json()
    assert all(p["id"]!=x["id"] for p in providers_b)

def test_project_stage_bumps_context(client,auth_a):
    p=client.post("/api/v1/projects",headers=auth_a,json={"name":"Loja"}).json()
    s=client.post(f"/api/v1/projects/{p['id']}/stages",headers=auth_a,json={"name":"Obra","sequence":6,"set_current":True})
    assert s.status_code==201
    after=client.get(f"/api/v1/projects/{p['id']}",headers=auth_a).json()
    assert after["context_version"]==p["context_version"]+1
    assert after["current_stage"]=="Obra"
