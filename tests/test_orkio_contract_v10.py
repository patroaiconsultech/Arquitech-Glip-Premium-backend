from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from glip.config import settings
from glip.integrations.orkio import client as orkio
from glip.integrations.orkio.contracts import (
    build_draft_capability_request,
    validate_draft_response,
    ContractViolation,
)

def request():
    return build_draft_capability_request(
        request_schema_version="ORKIO-CAPABILITY-REQUEST-1",
        tenant_id="tenant-a",
        source_environment="test",
        request_id="request-00000001",
        execution_id="execution-0000001",
        correlation_id="correlation-00001",
        idempotency_key="idem-key-0000000001",
        project_id="project-1",
        actor_user_id="user-a",
        context_version=7,
        source_refs=["glip-knowledge:k1:v1"],
        body={
            "instruction":"Solicitar confirmação de visita.",
            "recipient_role":"provider",
            "intent":"follow_up",
            "channel":"whatsapp",
            "facts":["A visita ainda depende de confirmação."],
            "constraints":["Não confirmar data."],
        },
    )

def response(req, **overrides):
    data={
        "schema_version":"ORKIO-RESPONSE-1",
        "message_id":"message-1",
        "request_id":req["request_id"],
        "execution_id":req["execution_id"],
        "correlation_id":req["correlation_id"],
        "tenant_id":req["tenant_id"],
        "source_platform":"orkio",
        "agent_id":"orkio",
        "agent_name":"Orkio",
        "display_name":"Orkio",
        "final_speaker":"Orkio",
        "turn_owner":"orkio",
        "ownership_locked":True,
        "capability_id":req["capability_id"],
        "capability_version":req["capability_version"],
        "status":"completed",
        "content":{
            "draft":"Rascunho.",
            "facts_used":[],
            "assumptions":[],
            "draft_only":True,
            "external_write_allowed":False,
            "external_write_executed":False,
            "human_approval_required":True,
        },
        "error":None,
        "token_usage":{"input_tokens":1,"output_tokens":1},
        "latency":10,
        "created_at":"2026-09-04T16:00:00Z",
    }
    data.update(overrides)
    return data

class FakeResponse:
    def __init__(self,status_code:int,payload=None,invalid_json=False):
        self.status_code=status_code
        self._payload=payload
        self._invalid_json=invalid_json
        self.request=httpx.Request("POST","https://orkio.example.invalid/execute")
    def json(self):
        if self._invalid_json:
            raise ValueError("invalid json")
        return self._payload
    def raise_for_status(self):
        if self.status_code>=400:
            raise httpx.HTTPStatusError("error",request=self.request,response=self)

class FakeClient:
    def __init__(self,responses,calls):
        self.responses=responses
        self.calls=calls
    def __enter__(self): return self
    def __exit__(self,*a): return False
    def post(self,url,json=None,headers=None):
        self.calls.append({"url":url,"json":json,"headers":headers})
        value=self.responses.pop(0)
        if isinstance(value,Exception):
            raise value
        return value

def configure_capability(monkeypatch):
    monkeypatch.setattr(settings,"orkio_mode","capability_v1")
    monkeypatch.setattr(settings,"orkio_base_url","https://orkio.example.invalid")
    monkeypatch.setattr(settings,"orkio_capability_execute_path","/execute")
    monkeypatch.setattr(settings,"orkio_m2m_token","synthetic-test-token")
    monkeypatch.setattr(settings,"orkio_max_attempts",2)
    monkeypatch.setattr(settings,"orkio_retry_backoff_seconds",0.0)
    monkeypatch.setattr(settings,"orkio_circuit_failure_threshold",2)
    monkeypatch.setattr(settings,"orkio_circuit_cooldown_seconds",10.0)
    orkio._reset_circuit_for_tests()

def install(monkeypatch,responses):
    calls=[]
    monkeypatch.setattr(
        orkio.httpx,
        "Client",
        lambda *a,**k: FakeClient(responses,calls),
    )
    return calls

def test_canonical_request_contains_minimum_governed_context():
    req=request()
    assert req["schema_version"]=="ORKIO-CAPABILITY-REQUEST-1"
    assert req["source_platform"]=="glip"
    assert req["tenant_id"]=="tenant-a"
    assert req["context"]["project_id"]=="project-1"
    assert req["governance"]["external_write_allowed"] is False
    assert req["governance"]["human_approval_required"] is True
    dumped=json.dumps(req)
    assert "storage_ref" not in dumped
    assert "client_name" not in dumped
    assert "document_content" not in dumped

@pytest.mark.parametrize("key,value,code",[
    ("tenant_id","tenant-b","orkio_contract_tenant_id_mismatch"),
    ("request_id","other-request","orkio_contract_request_id_mismatch"),
    ("execution_id","other-exec","orkio_contract_execution_id_mismatch"),
    ("correlation_id","other-corr","orkio_contract_correlation_id_mismatch"),
    ("schema_version","WRONG","orkio_contract_schema_mismatch"),
])
def test_identity_and_schema_mismatches_fail_closed(key,value,code):
    req=request()
    with pytest.raises(ContractViolation,match=code):
        validate_draft_response(
            response(req,**{key:value}),
            response_schema_version="ORKIO-RESPONSE-1",
            expected_request=req,
        )

def test_external_write_claim_fails_closed():
    req=request()
    bad=response(req)
    bad["content"]["external_write_executed"]=True
    with pytest.raises(ContractViolation,match="external_write_executed"):
        validate_draft_response(
            bad,
            response_schema_version="ORKIO-RESPONSE-1",
            expected_request=req,
        )

def test_ownership_must_be_locked():
    req=request()
    with pytest.raises(ContractViolation,match="ownership_not_locked"):
        validate_draft_response(
            response(req,ownership_locked=False),
            response_schema_version="ORKIO-RESPONSE-1",
            expected_request=req,
        )

@pytest.mark.parametrize("status", [401,403])
def test_401_403_are_never_retried(monkeypatch,status):
    configure_capability(monkeypatch)
    req=request()
    calls=install(monkeypatch,[FakeResponse(status,{})])
    with pytest.raises(orkio.OrkioAdapterError,match="orkio_auth_rejected"):
        orkio.draft(req)
    assert len(calls)==1

@pytest.mark.parametrize("status", [502,503,504])
def test_transient_upstream_status_retries_once(monkeypatch,status):
    configure_capability(monkeypatch)
    req=request()
    calls=install(monkeypatch,[FakeResponse(status,{}),FakeResponse(200,response(req))])
    result=orkio.draft(req)
    assert result.retry_count==1
    assert len(calls)==2
    assert calls[0]["json"]==calls[1]["json"]==req

def test_timeout_retries_once_with_same_payload(monkeypatch):
    configure_capability(monkeypatch)
    req=request()
    timeout=httpx.ReadTimeout("timeout",request=httpx.Request("POST","https://x"))
    calls=install(monkeypatch,[timeout,FakeResponse(200,response(req))])
    result=orkio.draft(req)
    assert result.retry_count==1
    assert len(calls)==2
    assert calls[0]["json"]==calls[1]["json"]

def test_invalid_json_fails_closed_without_retry(monkeypatch):
    configure_capability(monkeypatch)
    req=request()
    calls=install(monkeypatch,[FakeResponse(200,invalid_json=True),FakeResponse(200,response(req))])
    with pytest.raises(orkio.OrkioAdapterError,match="invalid_json"):
        orkio.draft(req)
    assert len(calls)==1

def test_contract_violation_fails_closed_without_retry(monkeypatch):
    configure_capability(monkeypatch)
    req=request()
    bad=response(req,tenant_id="tenant-b")
    calls=install(monkeypatch,[FakeResponse(200,bad),FakeResponse(200,response(req))])
    with pytest.raises(orkio.OrkioAdapterError,match="tenant_id_mismatch"):
        orkio.draft(req)
    assert len(calls)==1

def test_circuit_opens_after_retryable_failures_and_recovers(monkeypatch):
    configure_capability(monkeypatch)
    req=request()
    calls=install(monkeypatch,[
        FakeResponse(503,{}),FakeResponse(503,{}),
        FakeResponse(503,{}),FakeResponse(503,{}),
    ])
    with pytest.raises(orkio.OrkioAdapterError):
        orkio.draft(req)
    with pytest.raises(orkio.OrkioAdapterError):
        orkio.draft(req)
    with pytest.raises(orkio.CircuitOpen):
        orkio.draft(req)

    # Recovery after cooldown is proven by moving monotonic time forward.
    monkeypatch.setattr(orkio,"monotonic",lambda:999999.0)
    monkeypatch.setattr(orkio,"_opened_at",0.0)
    # Resetting opened_at to an old instant simulates elapsed cooldown without sleep.
    calls2=install(monkeypatch,[FakeResponse(200,response(req))])
    result=orkio.draft(req)
    assert result.data["draft"]=="Rascunho."
    assert len(calls2)==1

def test_token_is_header_only_and_not_inside_payload(monkeypatch):
    configure_capability(monkeypatch)
    req=request()
    calls=install(monkeypatch,[FakeResponse(200,response(req))])
    orkio.draft(req)
    assert calls[0]["headers"]["Authorization"]=="Bearer synthetic-test-token"
    assert "synthetic-test-token" not in json.dumps(calls[0]["json"])

def test_source_contains_no_secret_logging():
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    source=(root/"src/glip/integrations/orkio/client.py").read_text(encoding="utf-8")
    assert "print(settings.orkio_m2m_token)" not in source
    assert "logger" not in source



@pytest.mark.parametrize("status", [400,404,409,422])
def test_contract_http_failures_are_terminal_and_never_retried(monkeypatch,status):
    configure_capability(monkeypatch)
    req=request()
    calls=install(monkeypatch,[FakeResponse(status,{}),FakeResponse(200,response(req))])
    with pytest.raises(orkio.OrkioAdapterError,match=f"orkio_upstream_contract_rejected_{status}"):
        orkio.draft(req)
    assert len(calls)==1


@pytest.mark.parametrize("status", [500,501])
def test_nonretryable_upstream_5xx_are_terminal(monkeypatch,status):
    configure_capability(monkeypatch)
    req=request()
    calls=install(monkeypatch,[FakeResponse(status,{}),FakeResponse(200,response(req))])
    with pytest.raises(orkio.OrkioAdapterError,match=f"orkio_upstream_terminal_{status}"):
        orkio.draft(req)
    assert len(calls)==1


@pytest.mark.parametrize("status", [408,429])
def test_additional_transient_statuses_retry_once(monkeypatch,status):
    configure_capability(monkeypatch)
    req=request()
    calls=install(monkeypatch,[FakeResponse(status,{}),FakeResponse(200,response(req))])
    result=orkio.draft(req)
    assert result.retry_count==1
    assert len(calls)==2
