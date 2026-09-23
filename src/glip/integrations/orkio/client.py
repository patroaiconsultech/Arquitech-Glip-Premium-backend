from __future__ import annotations

from datetime import datetime, timezone
from time import perf_counter, monotonic, sleep
from threading import Lock
import httpx

from .contracts import AdapterResult, ContractViolation, validate_draft_response
from .retry_policy import HttpFailureClass, classify_http_failure
from ...config import settings

class OrkioAdapterError(RuntimeError):
    pass

class CircuitOpen(OrkioAdapterError):
    pass

_lock=Lock()
_failures=0
_opened_at=0.0

def _circuit_before_call():
    global _failures,_opened_at
    with _lock:
        if _failures < settings.orkio_circuit_failure_threshold:
            return
        if monotonic()-_opened_at >= settings.orkio_circuit_cooldown_seconds:
            _failures=0
            _opened_at=0.0
            return
        raise CircuitOpen("orkio_circuit_open")

def _circuit_success():
    global _failures,_opened_at
    with _lock:
        _failures=0
        _opened_at=0.0

def _circuit_failure():
    global _failures,_opened_at
    with _lock:
        _failures+=1
        if _failures >= settings.orkio_circuit_failure_threshold:
            _opened_at=monotonic()

def _reset_circuit_for_tests():
    global _failures,_opened_at
    with _lock:
        _failures=0
        _opened_at=0.0

def _mock(payload:dict)->dict:
    instruction=str((payload.get("input") or {}).get("instruction") or "").strip()
    return {
        "schema_version":settings.orkio_response_contract_version,
        "message_id":f"mock-{payload['execution_id']}",
        "request_id":payload["request_id"],
        "execution_id":payload["execution_id"],
        "correlation_id":payload["correlation_id"],
        "tenant_id":payload["tenant_id"],
        "source_platform":"orkio",
        "agent_id":"orkio",
        "agent_name":"Orkio",
        "display_name":"Orkio",
        "final_speaker":"Orkio",
        "turn_owner":"orkio",
        "ownership_locked":True,
        "capability_id":payload["capability_id"],
        "capability_version":payload["capability_version"],
        "status":"completed",
        "content":{
            "draft":f"Rascunho para aprovação: {instruction}",
            "facts_used":[],
            "assumptions":[],
            "draft_only":True,
            "external_write_allowed":False,
            "external_write_executed":False,
            "human_approval_required":True,
        },
        "error":None,
        "token_usage":{"input_tokens":0,"output_tokens":0},
        "latency":0,
        "created_at":datetime.now(timezone.utc).isoformat(),
    }

def probe()->dict:
    if settings.orkio_mode=="disabled":
        return {
            "mode":"disabled","status":"disabled","reachable":False,
            "capability_execution":"blocked",
            "realtime":settings.realtime_mode,
            "voice":settings.voice_mode,
            "avatar":settings.avatar_mode,
        }
    if settings.orkio_mode=="mock":
        return {
            "mode":"mock","status":"connected","reachable":True,
            "capability_execution":"mock_only",
            "realtime":settings.realtime_mode,
            "voice":settings.voice_mode,
            "avatar":settings.avatar_mode,
        }

    started=perf_counter()
    base=settings.orkio_base_url.rstrip("/")
    results={}
    reachable=False
    status="offline"

    # Probe carries no project/client/document/prompt data and no M2M bearer.
    for name,path in (
        ("health","/api/v2/health"),
        ("readiness","/api/v2/ready"),
        ("governance","/api/v2/governance/status"),
    ):
        try:
            with httpx.Client(timeout=settings.orkio_probe_timeout_seconds) as http:
                response=http.get(base+path,headers={"X-Source-Platform":"glip"})
            reachable=True
            try:
                body=response.json()
            except Exception:
                body=None
            results[name]={"http_status":response.status_code,"body":body}
        except Exception:
            results[name]={"http_status":None,"body":None}

    if reachable:
        health=results.get("health",{}).get("http_status")
        ready=results.get("readiness",{}).get("http_status")
        status="connected" if health==200 and ready==200 else "degraded"

    return {
        "mode":settings.orkio_mode,
        "status":status,
        "reachable":reachable,
        "capability_execution":"available" if settings.orkio_mode=="capability_v1" else "blocked",
        "latency_ms":int((perf_counter()-started)*1000),
        "realtime":settings.realtime_mode,
        "voice":settings.voice_mode,
        "avatar":settings.avatar_mode,
        **results,
    }

def draft(canonical_request:dict)->AdapterResult:
    started=perf_counter()

    if settings.orkio_mode=="mock":
        if settings.environment not in {"development","test"}:
            raise OrkioAdapterError("mock_forbidden_outside_dev")
        upstream=_mock(canonical_request)
        normalized=validate_draft_response(
            upstream,
            response_schema_version=settings.orkio_response_contract_version,
            expected_request=canonical_request,
        )
        return AdapterResult(normalized,upstream,int((perf_counter()-started)*1000),0)

    if settings.orkio_mode!="capability_v1":
        raise OrkioAdapterError("orkio_capability_execution_disabled")
    if not settings.orkio_base_url or not settings.orkio_capability_execute_path:
        raise OrkioAdapterError("orkio_capability_not_configured")
    if not settings.orkio_m2m_token:
        raise OrkioAdapterError("orkio_m2m_not_configured")

    _circuit_before_call()
    url=settings.orkio_base_url.rstrip("/")+settings.orkio_capability_execute_path
    headers={
        "Content-Type":"application/json",
        "Authorization":f"Bearer {settings.orkio_m2m_token}",
        "X-Source-Platform":"glip",
        "X-Idempotency-Key":canonical_request["idempotency_key"],
        "X-Request-ID":canonical_request["request_id"],
        "X-Correlation-ID":canonical_request["correlation_id"],
        "X-Execution-ID":canonical_request["execution_id"],
    }

    retry_count=0
    last_error=None
    for attempt in range(settings.orkio_max_attempts):
        try:
            with httpx.Client(timeout=settings.orkio_timeout_seconds) as http:
                response=http.post(url,json=canonical_request,headers=headers)

            if response.status_code >= 400:
                failure_class = classify_http_failure(response.status_code)
                if failure_class is HttpFailureClass.AUTH_TERMINAL:
                    raise OrkioAdapterError("orkio_auth_rejected")
                if failure_class is HttpFailureClass.CONTRACT_TERMINAL:
                    raise OrkioAdapterError(
                        f"orkio_upstream_contract_rejected_{response.status_code}"
                    )
                if failure_class is HttpFailureClass.UPSTREAM_TERMINAL:
                    _circuit_failure()
                    raise OrkioAdapterError(
                        f"orkio_upstream_terminal_{response.status_code}"
                    )
                raise httpx.HTTPStatusError(
                    "retryable_orkio_status",
                    request=response.request,
                    response=response,
                )

            try:
                upstream=response.json()
            except Exception as exc:
                raise ContractViolation("orkio_contract_invalid_json") from exc

            normalized=validate_draft_response(
                upstream,
                response_schema_version=settings.orkio_response_contract_version,
                expected_request=canonical_request,
            )
            _circuit_success()
            return AdapterResult(
                normalized,
                upstream,
                int((perf_counter()-started)*1000),
                retry_count,
            )

        except OrkioAdapterError:
            # 401/403 and local configuration errors fail closed immediately.
            raise
        except ContractViolation as exc:
            # Contract violations are deterministic and are never retried.
            raise OrkioAdapterError(str(exc)) from exc
        except httpx.HTTPStatusError as exc:
            last_error=exc
            if attempt+1>=settings.orkio_max_attempts:
                break
            retry_count+=1
            sleep(settings.orkio_retry_backoff_seconds*(2**attempt))
        except (httpx.TimeoutException,httpx.NetworkError) as exc:
            last_error=exc
            if attempt+1>=settings.orkio_max_attempts:
                break
            retry_count+=1
            sleep(settings.orkio_retry_backoff_seconds*(2**attempt))
        except Exception as exc:
            last_error=exc
            break

    _circuit_failure()
    raise OrkioAdapterError("orkio_request_failed") from last_error
