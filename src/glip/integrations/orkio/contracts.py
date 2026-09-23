from __future__ import annotations

from dataclasses import dataclass
from typing import Any

@dataclass(frozen=True)
class AdapterResult:
    data: dict[str, Any]
    upstream: dict[str, Any]
    latency_ms: int
    retry_count: int

class ContractViolation(ValueError):
    pass

def _required_string(data:dict,key:str)->str:
    value=data.get(key)
    if not isinstance(value,str) or not value.strip():
        raise ContractViolation(f"orkio_contract_missing_{key}")
    return value

def build_draft_capability_request(
    *,
    request_schema_version:str,
    tenant_id:str,
    source_environment:str,
    request_id:str,
    execution_id:str,
    correlation_id:str,
    idempotency_key:str,
    project_id:str,
    actor_user_id:str,
    context_version:int,
    source_refs:list[str],
    body:dict,
)->dict:
    classification=str(body.get("data_classification") or "INTERNAL").upper()
    if classification not in {"PUBLIC","INTERNAL","CONFIDENTIAL"}:
        raise ContractViolation("orkio_request_data_classification_invalid")

    instruction=str(body.get("instruction") or "").strip()
    if not instruction:
        raise ContractViolation("orkio_request_instruction_required")

    facts=[str(x).strip() for x in (body.get("facts") or []) if str(x).strip()]
    constraints=[str(x).strip() for x in (body.get("constraints") or []) if str(x).strip()]

    # Deliberately minimal context. Client name, document content, storage refs and
    # the full GLIP ProjectContext are not sent implicitly.
    return {
        "schema_version":request_schema_version,
        "request_id":request_id,
        "execution_id":execution_id,
        "correlation_id":correlation_id,
        "idempotency_key":idempotency_key,
        "tenant_id":tenant_id,
        "source_platform":"glip",
        "source_environment":source_environment,
        "capability_id":"glip.draft_message",
        "capability_version":"1.0.0",
        "data_classification":classification,
        "context":{
            "organization_id":tenant_id,
            "project_id":project_id,
            "actor_user_id":actor_user_id,
            "context_version":str(context_version),
            "purpose":"draft_message",
            "source_refs":list(source_refs),
        },
        "input":{
            "schema_version":"glip.draft-message.input.v1",
            "instruction":instruction,
            "recipient_role":str(body.get("recipient_role") or "unspecified"),
            "intent":str(body.get("intent") or "draft"),
            "channel":str(body.get("channel") or "internal"),
            "facts":facts,
            "constraints":constraints,
            "tone":str(body.get("tone") or "professional"),
            "language":str(body.get("language") or "pt-BR"),
        },
        "governance":{
            "governance_mode":"human_approval",
            "write_allowed":False,
            "execution_allowed":True,
            "external_write_allowed":False,
            "human_approval_required":True,
            "draft_only":True,
        },
    }

def validate_draft_response(
    data:dict,
    *,
    response_schema_version:str,
    expected_request:dict,
    expected_source_platform:str="orkio",
)->dict:
    if not isinstance(data,dict):
        raise ContractViolation("orkio_contract_response_not_object")
    if data.get("schema_version") != response_schema_version:
        raise ContractViolation("orkio_contract_schema_mismatch")

    for key in (
        "message_id","request_id","execution_id","correlation_id","tenant_id",
        "source_platform","agent_id","agent_name","display_name","final_speaker",
        "turn_owner","capability_id","capability_version","status","created_at",
    ):
        _required_string(data,key)

    exact={
        "request_id":expected_request["request_id"],
        "execution_id":expected_request["execution_id"],
        "correlation_id":expected_request["correlation_id"],
        "tenant_id":expected_request["tenant_id"],
        "source_platform":expected_source_platform,
        "capability_id":expected_request["capability_id"],
        "capability_version":expected_request["capability_version"],
    }
    for key,value in exact.items():
        if data.get(key)!=value:
            raise ContractViolation(f"orkio_contract_{key}_mismatch")

    if data.get("ownership_locked") is not True:
        raise ContractViolation("orkio_contract_ownership_not_locked")
    if data.get("status")!="completed":
        raise ContractViolation("orkio_contract_status_not_completed")
    if data.get("error") not in (None,{}):
        raise ContractViolation("orkio_contract_completed_with_error")

    content=data.get("content")
    if not isinstance(content,dict):
        raise ContractViolation("orkio_contract_content_not_object")
    draft=content.get("draft")
    if not isinstance(draft,str) or not draft.strip():
        raise ContractViolation("orkio_contract_empty_draft")

    # Governance can appear in the canonical content. Any positive external write
    # claim is a hard contract violation.
    if data.get("external_write_allowed") is True:
        raise ContractViolation("orkio_contract_external_write_allowed")
    if content.get("external_write_allowed") is True:
        raise ContractViolation("orkio_contract_external_write_allowed")
    if content.get("external_write_executed") is True:
        raise ContractViolation("orkio_contract_external_write_executed")
    if content.get("draft_only") is not True:
        raise ContractViolation("orkio_contract_draft_only_required")
    if content.get("human_approval_required") is not True:
        raise ContractViolation("orkio_contract_human_approval_required")

    normalized={
        "draft":draft.strip(),
        "facts_used":list(content.get("facts_used") or []),
        "assumptions":list(content.get("assumptions") or []),
        "agent_id":data["agent_id"],
        "agent_name":data["agent_name"],
        "display_name":data["display_name"],
        "final_speaker":data["final_speaker"],
        "turn_owner":data["turn_owner"],
        "ownership_locked":True,
        "external_write_allowed":False,
        "human_approval_required":True,
        "draft_only":True,
    }
    return normalized
