from glip.integrations.orkio.contracts import AdapterResult
from glip import services


def test_external_orkio_call_occurs_after_db_transaction_is_closed(monkeypatch,client,db,auth_a):
    project=client.post("/api/v1/projects",headers=auth_a,json={"name":"Projeto"}).json()

    def fake_draft(canonical_request):
        assert db.in_transaction() is False
        upstream={
            "schema_version":"ORKIO-RESPONSE-1",
            "request_id":canonical_request["request_id"],
        }
        return AdapterResult(
            data={
                "draft":"Rascunho premium.",
                "facts_used":[],
                "assumptions":[],
                "agent_id":"orkio",
                "turn_owner":"orkio",
                "ownership_locked":True,
            },
            upstream=upstream,
            latency_ms=5,
            retry_count=0,
        )

    monkeypatch.setattr(services,"orkio_draft",fake_draft)
    r=client.post(
        f"/api/v1/projects/{project['id']}/capabilities/draft-message",
        headers={
            **auth_a,
            "X-Request-ID":"transaction-boundary-1",
            "X-Correlation-ID":"transaction-correlation-1",
        },
        json={
            "channel":"internal",
            "recipient_role":"provider",
            "intent":"draft",
            "instruction":"Preparar rascunho.",
            "source_refs":[],
        },
    )
    assert r.status_code==200
    assert r.json()["draft"]=="Rascunho premium."
