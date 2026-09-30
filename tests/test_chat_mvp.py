from glip import chat_routes


def _fake_reply(**kwargs):
    return "Resposta GLIP Intelligence", "test", "test-model"


def test_chat_thread_message_persists_and_is_tenant_scoped(client, auth_a, auth_b, monkeypatch):
    monkeypatch.setattr(chat_routes, "generate_reply", _fake_reply)

    project = client.post("/api/v1/projects", headers=auth_a, json={"name": "Projeto Chat"}).json()
    created = client.post(
        "/api/v1/chat/threads",
        headers=auth_a,
        json={"project_id": project["id"]},
    )
    assert created.status_code == 201
    thread_id = created.json()["id"]

    sent = client.post(
        f"/api/v1/chat/threads/{thread_id}/messages",
        headers=auth_a,
        json={"content": "Quais são as prioridades deste projeto?"},
    )
    assert sent.status_code == 200
    assert sent.json()["assistant_message"]["content"] == "Resposta GLIP Intelligence"

    messages = client.get(f"/api/v1/chat/threads/{thread_id}/messages", headers=auth_a)
    assert messages.status_code == 200
    assert [x["role"] for x in messages.json()] == ["user", "assistant"]

    hidden = client.get(f"/api/v1/chat/threads/{thread_id}/messages", headers=auth_b)
    assert hidden.status_code == 404


def test_chat_thread_rejects_cross_tenant_project(client, auth_a, auth_b):
    project = client.post("/api/v1/projects", headers=auth_b, json={"name": "Tenant B"}).json()
    response = client.post(
        "/api/v1/chat/threads",
        headers=auth_a,
        json={"project_id": project["id"]},
    )
    assert response.status_code == 404


def test_chat_empty_message_is_rejected(client, auth_a, monkeypatch):
    monkeypatch.setattr(chat_routes, "generate_reply", _fake_reply)
    created = client.post("/api/v1/chat/threads", headers=auth_a, json={})
    thread_id = created.json()["id"]
    response = client.post(
        f"/api/v1/chat/threads/{thread_id}/messages",
        headers=auth_a,
        json={"content": "   "},
    )
    assert response.status_code == 422
