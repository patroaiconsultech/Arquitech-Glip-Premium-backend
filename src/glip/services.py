import hashlib
from uuid import uuid4
from datetime import datetime, timezone
from sqlalchemy import select, func
from fastapi import HTTPException
from .models import (
    Project,Task,CognitiveExecution,Draft,DraftVersion,ApprovalRequest,ApprovalDecision,
    ProjectCognitiveProfile,ApprovedVersion,MemoryCandidate,ProjectMemoryFact,OutboxEvent,IntegrationExecution
)
from .context import project_or_404,build
from .risk import scan
from .integrations.orkio import draft as orkio_draft, OrkioAdapterError
from .integrations.orkio.contracts import build_draft_capability_request, ContractViolation
from .config import settings
from .integration_idempotency import (
    acquire_execution_lease,
    fail_execution_if_owner,
    finalize_execution_if_owner,
    commit_new_or_recover_winner,
    find_execution,
)

def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def stable_json_sha256(value: dict) -> str:
    import json
    raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def ensure_cognitive_profile(db, tenant_id: str, project_id: str) -> ProjectCognitiveProfile:
    profile = db.scalar(select(ProjectCognitiveProfile).where(
        ProjectCognitiveProfile.tenant_id==tenant_id,
        ProjectCognitiveProfile.project_id==project_id
    ))
    if profile:
        return profile
    profile = ProjectCognitiveProfile(
        tenant_id=tenant_id,
        project_id=project_id,
        baseline_id=settings.default_project_baseline_id,
        baseline_version=settings.default_project_baseline_version,
        policy_profile_id=settings.default_project_policy_id,
        voice_profile_id=settings.default_voice_profile_id,
        memory_namespace=f"glip:{tenant_id}:project:{project_id}",
        enabled_capabilities=["glip.project_summary.v1","glip.draft_message.v1","glip.risk_scan.v1"],
        status="active",
    )
    db.add(profile)
    db.flush()
    return profile

def summary(db, tenant: str, project_id: str) -> dict:
    project = project_or_404(db,tenant,project_id)
    tasks = db.scalars(select(Task).where(Task.tenant_id==tenant,Task.project_id==project_id)).all()
    pending = [t.title for t in tasks if t.status not in {"done","completed"}]
    return {
        "schema_version":"glip.project-summary.response.v1",
        "status":"completed",
        "summary":f"{project.name} está em status {project.status}. Há {len(pending)} tarefa(s) pendente(s).",
        "current_stage":project.current_stage,
        "progress":[t.title for t in tasks if t.status in {"done","completed"}],
        "pending_items":pending,
        "risks":[],
        "decisions_required":[],
        "next_actions":pending[:5],
        "sources_used":[],
        "unsupported_claims":[],
    }

def create_draft(db, tenant: str, project_id: str, actor: str, request_id: str, correlation_id: str, body: dict) -> dict:
    project = project_or_404(db,tenant,project_id)
    profile = ensure_cognitive_profile(db,tenant,project_id)
    context = build(db,tenant,project_id,actor,correlation_id,purpose="draft_message")
    requested = sorted(set(body.get("source_refs") or []))
    if not set(requested).issubset(set(context["source_refs"])):
        raise HTTPException(403,"source_ref_not_authorized")

    idempotency_key=f"glip-draft:{tenant}:{project_id}:{request_id}"
    request_material={
        "tenant_id":tenant,
        "project_id":project_id,
        "request_id":request_id,
        "capability_id":"glip.draft_message",
        "capability_version":"1.0.0",
        "project_context_version":project.context_version,
        "source_refs":requested,
        "body":body,
    }
    request_digest=stable_json_sha256(request_material)

    existing=find_execution(
        db,
        tenant_id=tenant,
        destination_service="orkio",
        idempotency_key=idempotency_key,
    )

    if existing is not None:
        if existing.request_sha256!=request_digest:
            raise HTTPException(409,"idempotency_key_reused_with_different_request")
        if existing.status=="completed" and existing.domain_response_json:
            replay=dict(existing.domain_response_json)
            replay["_idempotent_replay"]=True
            return replay
        if existing.status=="failed":
            raise HTTPException(502,"orkio_unavailable")
        canonical_request=dict(existing.request_json)
        draft=db.scalar(select(Draft).where(
            Draft.id==existing.draft_id,
            Draft.tenant_id==tenant,
            Draft.project_id==project_id,
        ))
        execution=db.scalar(select(CognitiveExecution).where(
            CognitiveExecution.id==existing.cognitive_execution_id,
            CognitiveExecution.tenant_id==tenant,
            CognitiveExecution.project_id==project_id,
        ))
        if not draft or not execution:
            raise HTTPException(409,"integration_idempotency_state_inconsistent")
        integration=existing
    else:
        # Local domain objects and the idempotency row are one transaction. If a
        # concurrent request wins the unique key, this whole loser transaction is
        # rolled back before the winner is reread.
        draft=Draft(
            tenant_id=tenant,project_id=project_id,status="contextualized",
            current_version=0,created_by=actor
        )
        execution=CognitiveExecution(
            tenant_id=tenant,project_id=project_id,request_id=request_id,
            correlation_id=correlation_id,capability_id="glip.draft_message",
            capability_version="1.0.0",project_context_version=project.context_version,
            status="contextualized",
        )
        db.add_all([draft,execution])
        db.flush()

        execution_id=str(uuid4())
        try:
            canonical_request=build_draft_capability_request(
                request_schema_version=settings.orkio_capability_contract_version,
                tenant_id=tenant,
                source_environment=settings.environment,
                request_id=request_id,
                execution_id=execution_id,
                correlation_id=correlation_id,
                idempotency_key=idempotency_key,
                project_id=project_id,
                actor_user_id=actor,
                context_version=project.context_version,
                source_refs=requested,
                body=body,
            )
        except ContractViolation as exc:
            raise HTTPException(422,str(exc)) from exc

        candidate=IntegrationExecution(
            tenant_id=tenant,
            project_id=project_id,
            destination_service="orkio",
            capability_id="glip.draft_message",
            capability_version="1.0.0",
            request_id=request_id,
            execution_id=execution_id,
            correlation_id=correlation_id,
            idempotency_key=idempotency_key,
            request_sha256=request_digest,
            request_json=canonical_request,
            draft_id=draft.id,
            cognitive_execution_id=execution.id,
            status="contextualized",
        )
        claim=commit_new_or_recover_winner(
            db,
            candidate=candidate,
            request_sha256=request_digest,
        )
        integration=claim.row

        if claim.disposition=="REPLAY":
            replay=dict(integration.domain_response_json or {})
            replay["_idempotent_replay"]=True
            return replay
        if claim.disposition=="FAILED":
            raise HTTPException(502,"orkio_unavailable")

        if claim.disposition=="IN_PROGRESS":
            # Our local Draft/CognitiveExecution objects were rolled back. Reload
            # the winner-owned objects before entering the lease state machine.
            canonical_request=dict(integration.request_json)
            draft=db.scalar(select(Draft).where(
                Draft.id==integration.draft_id,
                Draft.tenant_id==tenant,
                Draft.project_id==project_id,
            ))
            execution=db.scalar(select(CognitiveExecution).where(
                CognitiveExecution.id==integration.cognitive_execution_id,
                CognitiveExecution.tenant_id==tenant,
                CognitiveExecution.project_id==project_id,
            ))
            if not draft or not execution:
                raise HTTPException(409,"integration_idempotency_state_inconsistent")
        else:
            integration=candidate

    lease=acquire_execution_lease(
        db,
        row=integration,
        lease_seconds=settings.orkio_execution_lease_seconds,
    )
    integration=lease.row

    if lease.disposition=="REPLAY":
        replay=dict(integration.domain_response_json or {})
        replay["_idempotent_replay"]=True
        return replay
    if lease.disposition=="FAILED":
        raise HTTPException(502,"orkio_unavailable")
    if lease.disposition=="IN_PROGRESS":
        raise HTTPException(409,"idempotent_execution_in_progress")
    if lease.disposition!="ACQUIRED" or not lease.owner_token:
        raise HTTPException(409,"integration_execution_claim_conflict")

    owner_token=lease.owner_token
    canonical_request=dict(integration.request_json)
    execution.status="calling"
    draft.status="calling"
    db.commit()

    # The lease transition above is committed before any external call.
    try:
        adapter=orkio_draft(canonical_request)
    except OrkioAdapterError as exc:
        # The ledger failure transition is a CAS on live ownership. Domain state
        # is mutated in the same transaction; a stale owner cannot commit it.
        execution.status="failed"
        execution.error_code=str(exc)
        draft.status="failed"
        fail_execution_if_owner(
            db,
            execution_id=integration.id,
            tenant_id=tenant,
            owner_token=owner_token,
            error_code=str(exc),
        )
        db.commit()
        raise HTTPException(502,"orkio_unavailable") from exc

    content=adapter.data["draft"]
    risk=scan(content)
    draft.current_version=1
    draft.status="criticized"
    version=DraftVersion(
        tenant_id=tenant,project_id=project_id,draft_id=draft.id,version=1,
        content=content,content_sha256=sha(content),
        created_by_type="ai",created_by_id=adapter.data.get("agent_id") or "orkio",
        capability_id="glip.draft_message",capability_version="1.0.0",
        voice_profile_id=body.get("voice_profile_id") or profile.voice_profile_id,
        project_context_version=project.context_version,
        risk_scan=risk,source_refs=requested,
    )
    db.add(version)
    db.flush()

    execution.status="completed"
    execution.latency_ms=adapter.latency_ms
    execution.retry_count=adapter.retry_count

    domain_response={
        "schema_version":"glip.draft-message.response.v1",
        "status":"drafted",
        "draft_id":draft.id,
        "draft_version_id":version.id,
        "version":1,
        "draft":content,
        "facts_used":adapter.data.get("facts_used",[]),
        "assumptions":adapter.data.get("assumptions",[]),
        "risk_flags":risk["flags"],
        "approval_required":True,
        "external_write_allowed":False,
        "voice_profile_id":version.voice_profile_id,
        "request_id":request_id,
        "correlation_id":correlation_id,
        "retry_count":adapter.retry_count,
        "agent_id":adapter.data.get("agent_id"),
        "turn_owner":adapter.data.get("turn_owner"),
        "ownership_locked":adapter.data.get("ownership_locked") is True,
    }

    # The ledger completion transition and domain changes are committed together.
    # If ownership changed or the lease expired, the CAS rolls back this entire
    # transaction, so a stale owner cannot persist Draft/DraftVersion changes.
    finalize_execution_if_owner(
        db,
        execution_id=integration.id,
        tenant_id=tenant,
        owner_token=owner_token,
        upstream_response_json=adapter.upstream,
        domain_response_json=domain_response,
        latency_ms=adapter.latency_ms,
        retry_count=adapter.retry_count,
    )
    db.flush()
    return domain_response
def add_version(db, tenant: str, project_id: str, draft_id: str, actor: str, content: str):
    draft = db.scalar(select(Draft).where(
        Draft.id==draft_id,Draft.tenant_id==tenant,Draft.project_id==project_id
    ))
    if not draft:
        raise HTTPException(404,"draft_not_found")
    if not content.strip():
        raise HTTPException(422,"content_required")
    project = project_or_404(db,tenant,project_id)
    draft.current_version += 1
    draft.status = "criticized"
    version = DraftVersion(
        tenant_id=tenant,project_id=project_id,draft_id=draft.id,version=draft.current_version,
        content=content,content_sha256=sha(content),
        created_by_type="human",created_by_id=actor,
        capability_id="glip.draft_message",capability_version="1.0.0",
        voice_profile_id=settings.default_voice_profile_id,
        project_context_version=project.context_version,risk_scan=scan(content),source_refs=[]
    )
    db.add(version)
    for req in db.scalars(select(ApprovalRequest).where(
        ApprovalRequest.tenant_id==tenant,ApprovalRequest.draft_id==draft_id,
        ApprovalRequest.status=="awaiting_approval"
    )).all():
        req.status = "invalidated"
    db.flush()
    return version

def request_approval(db, tenant: str, project_id: str, draft_id: str, version_id: str, actor: str):
    draft = db.scalar(select(Draft).where(
        Draft.id==draft_id,Draft.tenant_id==tenant,Draft.project_id==project_id
    ))
    version = db.scalar(select(DraftVersion).where(
        DraftVersion.id==version_id,DraftVersion.draft_id==draft_id,
        DraftVersion.tenant_id==tenant,DraftVersion.project_id==project_id
    ))
    if not draft or not version:
        raise HTTPException(404,"draft_or_version_not_found")
    if version.version != draft.current_version:
        raise HTTPException(409,"approval_requires_current_version")
    request = ApprovalRequest(
        tenant_id=tenant,project_id=project_id,draft_id=draft_id,draft_version_id=version_id,
        requested_content_sha256=version.content_sha256,status="awaiting_approval",requested_by=actor
    )
    draft.status = "awaiting_approval"
    db.add(request)
    db.flush()
    return request

def decide(db, tenant: str, project_id: str, draft_id: str, version_id: str,
           actor: str, decision: str, reason: str|None=None, correlation_id: str|None=None):
    draft = db.scalar(select(Draft).where(
        Draft.id==draft_id,Draft.tenant_id==tenant,Draft.project_id==project_id
    ))
    version = db.scalar(select(DraftVersion).where(
        DraftVersion.id==version_id,DraftVersion.draft_id==draft_id,
        DraftVersion.tenant_id==tenant,DraftVersion.project_id==project_id
    ))
    request = db.scalar(select(ApprovalRequest).where(
        ApprovalRequest.tenant_id==tenant,ApprovalRequest.project_id==project_id,
        ApprovalRequest.draft_id==draft_id,ApprovalRequest.draft_version_id==version_id,
        ApprovalRequest.status=="awaiting_approval"
    ).order_by(ApprovalRequest.created_at.desc()))
    if not draft or not version or not request:
        raise HTTPException(404,"approval_request_not_found")
    if version.version != draft.current_version or sha(version.content) != request.requested_content_sha256:
        request.status = "invalidated"
        raise HTTPException(409,"approval_invalidated")

    request.status = decision
    draft.status = decision
    decision_obj = ApprovalDecision(
        tenant_id=tenant,project_id=project_id,approval_request_id=request.id,
        draft_id=draft_id,draft_version_id=version_id,decision=decision,
        approved_content_sha256=version.content_sha256 if decision=="approved" else None,
        actor_id=actor,reason=reason
    )
    db.add(decision_obj)
    db.flush()

    approved = None
    candidate = None
    if decision == "approved":
        approved = ApprovedVersion(
            tenant_id=tenant,project_id=project_id,draft_id=draft_id,draft_version_id=version_id,
            approval_decision_id=decision_obj.id,content=version.content,content_sha256=version.content_sha256,
            capability_id=version.capability_id,capability_version=version.capability_version,
            voice_profile_id=version.voice_profile_id,approved_by=actor
        )
        db.add(approved)
        db.flush()

        # Candidate only. It is NOT active memory until a human explicitly promotes a fact.
        candidate = MemoryCandidate(
            tenant_id=tenant,project_id=project_id,
            source_approved_version_id=approved.id,
            candidate_type="approved_communication_pattern",
            source_content_sha256=approved.content_sha256,
            status="pending",
        )
        db.add(candidate)
        db.add(OutboxEvent(
            tenant_id=tenant,project_id=project_id,event_type="project.draft.approved",
            event_version=1,correlation_id=correlation_id or str(uuid4()),
            causation_id=decision_obj.id,
            payload={"approved_version_id":approved.id,"draft_id":draft_id,"content_sha256":approved.content_sha256},
            status="pending",
        ))
        db.flush()

    return decision_obj, approved, candidate

def approve_memory_candidate(db, tenant: str, project_id: str, candidate_id: str,
                             actor: str, fact_key: str, fact_value: str, classification: str="INTERNAL"):
    candidate = db.scalar(select(MemoryCandidate).where(
        MemoryCandidate.id==candidate_id,MemoryCandidate.tenant_id==tenant,
        MemoryCandidate.project_id==project_id,MemoryCandidate.status=="pending"
    ))
    if not candidate:
        raise HTTPException(404,"memory_candidate_not_found")
    if not fact_key.strip() or not fact_value.strip():
        raise HTTPException(422,"fact_key_and_value_required")
    current_max = db.scalar(select(func.max(ProjectMemoryFact.version)).where(
        ProjectMemoryFact.tenant_id==tenant,
        ProjectMemoryFact.project_id==project_id,
        ProjectMemoryFact.fact_key==fact_key.strip()
    )) or 0
    fact = ProjectMemoryFact(
        tenant_id=tenant,project_id=project_id,fact_key=fact_key.strip(),fact_value=fact_value.strip(),
        classification=classification,version=current_max+1,status="active",
        source_approved_version_id=candidate.source_approved_version_id,approved_by=actor
    )
    candidate.status = "promoted"
    candidate.decided_by = actor
    candidate.decided_at = datetime.now(timezone.utc)
    db.add(fact)
    db.flush()
    return fact
