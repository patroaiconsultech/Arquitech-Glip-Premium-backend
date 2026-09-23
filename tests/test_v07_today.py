from datetime import datetime, timezone, timedelta

def test_today_dashboard_is_tenant_scoped_and_surfaces_operational_work(client,db,auth_a,auth_b):
    p=client.post("/api/v1/projects",headers=auth_a,json={"name":"Projeto A"}).json()
    other=client.post("/api/v1/projects",headers=auth_b,json={"name":"Projeto B"}).json()

    due=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    client.post(f"/api/v1/projects/{p['id']}/tasks",headers=auth_a,json={"title":"Tarefa atrasada","due_at":due})
    client.post(f"/api/v1/projects/{p['id']}/decisions",headers=auth_a,json={"title":"Escolher acabamento"})
    client.post(f"/api/v1/projects/{other['id']}/decisions",headers=auth_b,json={"title":"Decisão B"})

    r=client.get("/api/v1/dashboard/today",headers=auth_a)
    assert r.status_code==200
    body=r.json()
    assert body["tenant_id"]=="tenant-a"
    assert body["counts"]["projects"]==1
    assert body["counts"]["open_decisions"]==1
    assert all(x["project_id"]==p["id"] for x in body["open_decisions"])
    assert all(x["id"]!=other["id"] for x in body["risk_projects"])

def test_project_provider_list_does_not_cross_tenant(client,db,auth_a,auth_b):
    p=client.post("/api/v1/projects",headers=auth_a,json={"name":"Projeto"}).json()
    provider=client.post("/api/v1/providers",headers=auth_a,json={"name":"Fornecedor A"}).json()
    assert client.post(f"/api/v1/projects/{p['id']}/providers/{provider['id']}",headers=auth_a).status_code==201
    rows=client.get(f"/api/v1/projects/{p['id']}/providers",headers=auth_a)
    assert rows.status_code==200 and len(rows.json())==1
    assert client.get(f"/api/v1/projects/{p['id']}/providers",headers=auth_b).status_code==404
