from uuid import uuid4
from datetime import datetime, timezone, timedelta
from difflib import unified_diff
from fastapi import APIRouter,Depends,Header,HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .auth import get_principal,Principal
from .database import get_db
from .models import (
    Client,Project,ProjectStage,Provider,ProjectProvider,Task,Milestone,ScheduleItem,BudgetSnapshot,
    Draft,DraftVersion,ApprovalRequest,ApprovedVersion,ProjectKnowledgeItem,ProjectMemoryFact,
    MemoryCandidate,CognitiveExecution,OutboxEvent,Document,ProjectDecision,ProjectAsset,ProjectCommunication
)
from .context import project_or_404,build
from .services import summary,create_draft,add_version,request_approval,decide,ensure_cognitive_profile,approve_memory_candidate
from .risk import scan
from .audit import emit
from .config import settings
from .integrations.orkio import probe as orkio_probe

router=APIRouter(prefix="/api/v1")

def _corr(value: str|None) -> str:
    return value or str(uuid4())

def _dt(value):
    if value in (None,""):
        return None
    if isinstance(value,datetime):
        return value
    try:
        parsed=datetime.fromisoformat(str(value).replace("Z","+00:00"))
    except ValueError as exc:
        raise HTTPException(422,"datetime_invalid") from exc
    return parsed

def _cmp_dt(value):
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value

@router.get("/me")
def me(p:Principal=Depends(get_principal)):
    return {"subject":p.subject,"tenant_id":p.tenant_id,"role":p.role,"display_name":p.display_name}

@router.get("/clients")
def clients(p=Depends(get_principal),db:Session=Depends(get_db)):
    return db.scalars(select(Client).where(Client.tenant_id==p.tenant_id).order_by(Client.name)).all()

@router.post("/clients",status_code=201)
def create_client(body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    name=str(body.get("name") or "").strip()
    if not name: raise HTTPException(422,"name_required")
    obj=Client(tenant_id=p.tenant_id,name=name,email=body.get("email"),phone=body.get("phone"),notes=body.get("notes"))
    db.add(obj);db.commit();db.refresh(obj);return obj

@router.get("/projects")
def projects(p=Depends(get_principal),db:Session=Depends(get_db)):
    return db.scalars(select(Project).where(Project.tenant_id==p.tenant_id).order_by(Project.updated_at.desc())).all()

@router.post("/projects",status_code=201)
def create_project(body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    obj=Project(
        tenant_id=p.tenant_id,name=str(body.get("name") or "").strip(),code=body.get("code"),
        client_id=body.get("client_id"),description=body.get("description"),
        address_summary=body.get("address_summary"),created_by=p.subject
    )
    if not obj.name: raise HTTPException(422,"name_required")
    if obj.client_id and not db.scalar(select(Client).where(Client.id==obj.client_id,Client.tenant_id==p.tenant_id)):
        raise HTTPException(400,"client_not_found")
    db.add(obj);db.flush()
    profile=ensure_cognitive_profile(db,p.tenant_id,obj.id)
    emit(db,tenant_id=p.tenant_id,project_id=obj.id,actor_id=p.subject,event_type="project.created",
         payload={"cognitive_profile_id":profile.id})
    db.commit();db.refresh(obj);return obj

@router.get("/projects/{project_id}")
def get_project(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    return project_or_404(db,p.tenant_id,project_id)

@router.get("/projects/{project_id}/cognitive-profile")
def cognitive_profile(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    profile=ensure_cognitive_profile(db,p.tenant_id,project_id)
    db.commit();return profile

@router.post("/projects/{project_id}/stages",status_code=201)
def create_stage(project_id:str,body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    project=project_or_404(db,p.tenant_id,project_id)
    name=str(body.get("name") or "").strip()
    if not name: raise HTTPException(422,"name_required")
    obj=ProjectStage(tenant_id=p.tenant_id,project_id=project_id,name=name,
                     sequence=int(body.get("sequence") or 0),status=str(body.get("status") or "pending"))
    project.context_version+=1
    if body.get("set_current") is True: project.current_stage=name
    db.add(obj);db.commit();db.refresh(obj);return obj

@router.get("/providers")
def providers(p=Depends(get_principal),db:Session=Depends(get_db)):
    return db.scalars(select(Provider).where(Provider.tenant_id==p.tenant_id,Provider.active.is_(True)).order_by(Provider.name)).all()

@router.post("/providers",status_code=201)
def create_provider(body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    name=str(body.get("name") or "").strip()
    if not name: raise HTTPException(422,"name_required")
    obj=Provider(tenant_id=p.tenant_id,name=name,email=body.get("email"),phone=body.get("phone"),specialty=body.get("specialty"))
    db.add(obj);db.commit();db.refresh(obj);return obj

@router.post("/projects/{project_id}/providers/{provider_id}",status_code=201)
def link_provider(project_id:str,provider_id:str,body:dict|None=None,p=Depends(get_principal),db:Session=Depends(get_db)):
    project=project_or_404(db,p.tenant_id,project_id)
    provider=db.scalar(select(Provider).where(Provider.id==provider_id,Provider.tenant_id==p.tenant_id,Provider.active.is_(True)))
    if not provider: raise HTTPException(404,"provider_not_found")
    existing=db.scalar(select(ProjectProvider).where(
        ProjectProvider.tenant_id==p.tenant_id,ProjectProvider.project_id==project_id,ProjectProvider.provider_id==provider_id
    ))
    if existing: return existing
    obj=ProjectProvider(tenant_id=p.tenant_id,project_id=project_id,provider_id=provider_id,role=(body or {}).get("role"),active=True)
    project.context_version+=1;db.add(obj);db.commit();db.refresh(obj);return obj

@router.post("/projects/{project_id}/tasks",status_code=201)
def create_task(project_id:str,body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    project=project_or_404(db,p.tenant_id,project_id)
    title=str(body.get("title") or "").strip()
    if not title: raise HTTPException(422,"title_required")
    obj=Task(tenant_id=p.tenant_id,project_id=project_id,title=title,status=str(body.get("status") or "open"),due_at=_dt(body.get("due_at")))
    project.context_version+=1;db.add(obj);db.commit();db.refresh(obj);return obj

@router.post("/projects/{project_id}/milestones",status_code=201)
def create_milestone(project_id:str,body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    project=project_or_404(db,p.tenant_id,project_id)
    title=str(body.get("title") or "").strip()
    if not title: raise HTTPException(422,"title_required")
    obj=Milestone(tenant_id=p.tenant_id,project_id=project_id,title=title,status=str(body.get("status") or "planned"),due_at=_dt(body.get("due_at")))
    project.context_version+=1;db.add(obj);db.commit();db.refresh(obj);return obj

@router.post("/projects/{project_id}/schedule",status_code=201)
def create_schedule(project_id:str,body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    project=project_or_404(db,p.tenant_id,project_id)
    title=str(body.get("title") or "").strip()
    if not title: raise HTTPException(422,"title_required")
    obj=ScheduleItem(
        tenant_id=p.tenant_id,project_id=project_id,title=title,category=str(body.get("category") or "project"),
        status=str(body.get("status") or "planned"),starts_at=_dt(body.get("starts_at")),ends_at=_dt(body.get("ends_at")),
        owner_ref=body.get("owner_ref")
    )
    project.context_version+=1;db.add(obj);db.commit();db.refresh(obj);return obj

@router.get("/projects/{project_id}/schedule")
def list_schedule(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(ScheduleItem).where(
        ScheduleItem.tenant_id==p.tenant_id,ScheduleItem.project_id==project_id
    ).order_by(ScheduleItem.starts_at)).all()

@router.post("/projects/{project_id}/budgets",status_code=201)
def create_budget(project_id:str,body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    project=project_or_404(db,p.tenant_id,project_id)
    amount=int(body.get("amount_cents") or 0)
    if amount < 0: raise HTTPException(422,"amount_cents_must_be_nonnegative")
    # V0.5 never auto-approves financial data. Every new snapshot starts as draft.
    obj=BudgetSnapshot(
        tenant_id=p.tenant_id,project_id=project_id,label=str(body.get("label") or "Budget snapshot"),
        currency=str(body.get("currency") or "BRL"),amount_cents=amount,status="draft",
        notes=body.get("notes"),created_by=p.subject
    )
    project.context_version+=1;db.add(obj);db.commit();db.refresh(obj);return obj

@router.get("/projects/{project_id}/budgets")
def budgets(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(BudgetSnapshot).where(
        BudgetSnapshot.tenant_id==p.tenant_id,BudgetSnapshot.project_id==project_id
    ).order_by(BudgetSnapshot.created_at.desc())).all()

@router.post("/projects/{project_id}/knowledge",status_code=201)
def create_knowledge(project_id:str,body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    project=project_or_404(db,p.tenant_id,project_id)
    key=str(body.get("knowledge_key") or "").strip()
    summary=str(body.get("summary") or "").strip()
    source_ref=str(body.get("source_ref") or "").strip()
    if not key or not summary or not source_ref: raise HTTPException(422,"knowledge_key_summary_source_ref_required")
    obj=ProjectKnowledgeItem(
        tenant_id=p.tenant_id,project_id=project_id,knowledge_key=key,summary=summary,source_ref=source_ref,
        classification=str(body.get("classification") or "INTERNAL"),
        allowed_purposes=list(body.get("allowed_purposes") or []),version=int(body.get("version") or 1),
        status="active",approved_by=p.subject,expires_at=body.get("expires_at")
    )
    project.context_version+=1;db.add(obj);db.commit();db.refresh(obj);return obj

@router.get("/projects/{project_id}/knowledge")
def knowledge(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(ProjectKnowledgeItem).where(
        ProjectKnowledgeItem.tenant_id==p.tenant_id,ProjectKnowledgeItem.project_id==project_id
    )).all()

@router.get("/projects/{project_id}/memory")
def memory(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(ProjectMemoryFact).where(
        ProjectMemoryFact.tenant_id==p.tenant_id,ProjectMemoryFact.project_id==project_id,
        ProjectMemoryFact.status=="active"
    )).all()

@router.get("/projects/{project_id}/memory/candidates")
def memory_candidates(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(MemoryCandidate).where(
        MemoryCandidate.tenant_id==p.tenant_id,MemoryCandidate.project_id==project_id
    ).order_by(MemoryCandidate.created_at.desc())).all()

@router.post("/projects/{project_id}/memory/candidates/{candidate_id}/promote",status_code=201)
def promote_memory(project_id:str,candidate_id:str,body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    project=project_or_404(db,p.tenant_id,project_id)
    fact=approve_memory_candidate(
        db,p.tenant_id,project_id,candidate_id,p.subject,
        str(body.get("fact_key") or ""),str(body.get("fact_value") or ""),
        str(body.get("classification") or "INTERNAL")
    )
    project.context_version+=1
    emit(db,tenant_id=p.tenant_id,project_id=project_id,actor_id=p.subject,event_type="memory.promoted",
         payload={"memory_fact_id":fact.id,"candidate_id":candidate_id})
    db.commit();db.refresh(fact);return fact

@router.get("/projects/{project_id}/context")
def context(project_id:str,purpose:str="general",x_correlation_id:str|None=Header(None),
            p=Depends(get_principal),db:Session=Depends(get_db)):
    return build(db,p.tenant_id,project_id,p.subject,_corr(x_correlation_id),purpose=purpose)

@router.post("/projects/{project_id}/capabilities/project-summary")
def cap_summary(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    return summary(db,p.tenant_id,project_id)

@router.post("/projects/{project_id}/capabilities/risk-scan")
def cap_risk(project_id:str,body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return scan(str(body.get("content") or ""))

@router.post("/projects/{project_id}/capabilities/draft-message")
def cap_draft(project_id:str,body:dict,x_request_id:str|None=Header(None),x_correlation_id:str|None=Header(None),
              p=Depends(get_principal),db:Session=Depends(get_db)):
    request_id=x_request_id or str(uuid4());correlation_id=_corr(x_correlation_id)
    out=create_draft(db,p.tenant_id,project_id,p.subject,request_id,correlation_id,body)
    replay=bool(out.pop("_idempotent_replay",False))
    if not replay:
        emit(db,tenant_id=p.tenant_id,project_id=project_id,actor_id=p.subject,event_type="draft.created",
             correlation_id=correlation_id,payload={"draft_id":out["draft_id"],"version":out["version"]})
        db.commit()
    return out

@router.get("/projects/{project_id}/drafts")
def drafts(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(Draft).where(
        Draft.tenant_id==p.tenant_id,Draft.project_id==project_id
    ).order_by(Draft.updated_at.desc())).all()

@router.get("/projects/{project_id}/drafts/{draft_id}")
def draft_detail(project_id:str,draft_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    draft=db.scalar(select(Draft).where(Draft.id==draft_id,Draft.tenant_id==p.tenant_id,Draft.project_id==project_id))
    if not draft: raise HTTPException(404,"draft_not_found")
    versions=db.scalars(select(DraftVersion).where(
        DraftVersion.draft_id==draft_id,DraftVersion.tenant_id==p.tenant_id
    ).order_by(DraftVersion.version)).all()
    return {"id":draft.id,"status":draft.status,"current_version":draft.current_version,"versions":versions}

@router.get("/projects/{project_id}/drafts/{draft_id}/diff")
def draft_diff(project_id:str,draft_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    versions=db.scalars(select(DraftVersion).where(
        DraftVersion.draft_id==draft_id,DraftVersion.tenant_id==p.tenant_id,
        DraftVersion.project_id==project_id
    ).order_by(DraftVersion.version)).all()
    if len(versions)<2: return {"from_version":None,"to_version":versions[-1].version if versions else None,"diff":[]}
    a,b=versions[-2],versions[-1]
    diff=list(unified_diff(a.content.splitlines(),b.content.splitlines(),fromfile=f"v{a.version}",tofile=f"v{b.version}",lineterm=""))
    return {"from_version":a.version,"to_version":b.version,"diff":diff}

@router.post("/projects/{project_id}/drafts/{draft_id}/versions",status_code=201)
def edit(project_id:str,draft_id:str,body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    version=add_version(db,p.tenant_id,project_id,draft_id,p.subject,str(body.get("content") or ""))
    db.commit();db.refresh(version);return version

@router.post("/projects/{project_id}/drafts/{draft_id}/request-approval")
def request(project_id:str,draft_id:str,body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    req=request_approval(db,p.tenant_id,project_id,draft_id,str(body.get("draft_version_id") or ""),p.subject)
    db.commit();db.refresh(req);return req

@router.post("/projects/{project_id}/drafts/{draft_id}/approve")
def approve(project_id:str,draft_id:str,body:dict,x_correlation_id:str|None=Header(None),
            p=Depends(get_principal),db:Session=Depends(get_db)):
    decision,approved,candidate=decide(
        db,p.tenant_id,project_id,draft_id,str(body.get("draft_version_id") or ""),
        p.subject,"approved",body.get("reason"),_corr(x_correlation_id)
    )
    emit(db,tenant_id=p.tenant_id,project_id=project_id,actor_id=p.subject,event_type="draft.approved",
         correlation_id=x_correlation_id,payload={"approved_version_id":approved.id if approved else None})
    db.commit()
    return {"status":"approved","approval_decision_id":decision.id,"approved_version_id":approved.id,
            "memory_candidate_id":candidate.id,"content_sha256":approved.content_sha256}

@router.post("/projects/{project_id}/drafts/{draft_id}/reject")
def reject(project_id:str,draft_id:str,body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    decision,_,_=decide(db,p.tenant_id,project_id,draft_id,str(body.get("draft_version_id") or ""),p.subject,"rejected",body.get("reason"))
    db.commit();return {"status":"rejected","approval_decision_id":decision.id}

@router.get("/projects/{project_id}/approved-versions")
def approved_versions(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(ApprovedVersion).where(
        ApprovedVersion.tenant_id==p.tenant_id,ApprovedVersion.project_id==project_id
    ).order_by(ApprovedVersion.approved_at.desc())).all()

@router.get("/approvals")
def approvals(p=Depends(get_principal),db:Session=Depends(get_db)):
    return db.scalars(select(ApprovalRequest).where(
        ApprovalRequest.tenant_id==p.tenant_id,ApprovalRequest.status=="awaiting_approval"
    ).order_by(ApprovalRequest.created_at.desc())).all()

@router.get("/projects/{project_id}/executions")
def executions(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(CognitiveExecution).where(
        CognitiveExecution.tenant_id==p.tenant_id,CognitiveExecution.project_id==project_id
    ).order_by(CognitiveExecution.created_at.desc())).all()

@router.get("/projects/{project_id}/outbox")
def outbox(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(OutboxEvent).where(
        OutboxEvent.tenant_id==p.tenant_id,OutboxEvent.project_id==project_id
    ).order_by(OutboxEvent.created_at.desc())).all()


@router.get("/system/status")
def system_status(p=Depends(get_principal)):
    return {
        "service":"glip-backend",
        "release_id":settings.release_id,
        "tenant_id":p.tenant_id,
        "auth_mode":settings.auth_mode,
        "intelligence":{"mode":settings.orkio_mode},
        "realtime":{"mode":settings.realtime_mode,"blocking":False},
        "voice":{"mode":settings.voice_mode,"blocking":False},
        "avatar":{"mode":settings.avatar_mode,"blocking":False},
    }

@router.get("/integrations/orkio/status")
def integration_status(p=Depends(get_principal)):
    status=orkio_probe()
    status["tenant_id"]=p.tenant_id
    return status

@router.get("/projects/{project_id}/overview")
def project_overview(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project=project_or_404(db,p.tenant_id,project_id)
    def count(model):
        return len(db.scalars(select(model).where(
            model.tenant_id==p.tenant_id,
            model.project_id==project_id
        )).all())
    return {
        "project_id":project.id,
        "status":project.status,
        "current_stage":project.current_stage,
        "context_version":project.context_version,
        "counts":{
            "stages":count(ProjectStage),
            "tasks":count(Task),
            "milestones":count(Milestone),
            "schedule":count(ScheduleItem),
            "budgets":count(BudgetSnapshot),
            "documents":count(Document),
            "decisions":count(ProjectDecision),
            "assets":count(ProjectAsset),
            "communications":count(ProjectCommunication),
            "drafts":count(Draft),
        },
        "external_capabilities":{
            "intelligence":settings.orkio_mode,
            "realtime":settings.realtime_mode,
            "voice":settings.voice_mode,
            "avatar":settings.avatar_mode,
        }
    }

@router.get("/projects/{project_id}/stages")
def stages(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(ProjectStage).where(
        ProjectStage.tenant_id==p.tenant_id,ProjectStage.project_id==project_id
    ).order_by(ProjectStage.sequence)).all()

@router.get("/projects/{project_id}/tasks")
def tasks(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(Task).where(
        Task.tenant_id==p.tenant_id,Task.project_id==project_id
    )).all()

@router.get("/projects/{project_id}/milestones")
def milestones(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(Milestone).where(
        Milestone.tenant_id==p.tenant_id,Milestone.project_id==project_id
    )).all()

@router.get("/projects/{project_id}/documents")
def documents(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(Document).where(
        Document.tenant_id==p.tenant_id,Document.project_id==project_id
    )).all()

@router.post("/projects/{project_id}/documents",status_code=201)
def create_document(project_id:str,body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    project=project_or_404(db,p.tenant_id,project_id)
    name=str(body.get("name") or "").strip()
    storage_ref=str(body.get("storage_ref") or "").strip()
    if not name or not storage_ref:
        raise HTTPException(422,"name_storage_ref_required")
    obj=Document(
        tenant_id=p.tenant_id,project_id=project_id,name=name,storage_ref=storage_ref,
        classification=str(body.get("classification") or "project_internal"),
        allowed_purposes=list(body.get("allowed_purposes") or []),
        version=int(body.get("version") or 1),active=body.get("active",True)
    )
    project.context_version+=1
    db.add(obj);db.commit();db.refresh(obj);return obj

@router.get("/projects/{project_id}/decisions")
def decisions(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(ProjectDecision).where(
        ProjectDecision.tenant_id==p.tenant_id,ProjectDecision.project_id==project_id
    ).order_by(ProjectDecision.created_at.desc())).all()

@router.post("/projects/{project_id}/decisions",status_code=201)
def create_decision(project_id:str,body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    project=project_or_404(db,p.tenant_id,project_id)
    title=str(body.get("title") or "").strip()
    if not title: raise HTTPException(422,"title_required")
    obj=ProjectDecision(
        tenant_id=p.tenant_id,project_id=project_id,title=title,
        status=str(body.get("status") or "open"),
        decision=body.get("decision"),rationale=body.get("rationale"),
        created_by=p.subject
    )
    project.context_version+=1
    db.add(obj);db.commit();db.refresh(obj);return obj

@router.get("/projects/{project_id}/assets")
def assets(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(ProjectAsset).where(
        ProjectAsset.tenant_id==p.tenant_id,ProjectAsset.project_id==project_id
    ).order_by(ProjectAsset.created_at.desc())).all()

@router.post("/projects/{project_id}/assets",status_code=201)
def create_asset(project_id:str,body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    project=project_or_404(db,p.tenant_id,project_id)
    name=str(body.get("name") or "").strip()
    storage_ref=str(body.get("storage_ref") or "").strip()
    asset_type=str(body.get("asset_type") or "media").strip()
    if asset_type not in {"media","3d","bim","reference"}:
        raise HTTPException(422,"asset_type_invalid")
    if not name or not storage_ref:
        raise HTTPException(422,"name_storage_ref_required")
    obj=ProjectAsset(
        tenant_id=p.tenant_id,project_id=project_id,asset_type=asset_type,
        name=name,storage_ref=storage_ref,mime_type=body.get("mime_type"),
        version=int(body.get("version") or 1),
        classification=str(body.get("classification") or "project_internal"),
        metadata_json=dict(body.get("metadata") or {}),
        created_by=p.subject
    )
    project.context_version+=1
    db.add(obj);db.commit();db.refresh(obj);return obj

@router.get("/projects/{project_id}/communications")
def communications(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    return db.scalars(select(ProjectCommunication).where(
        ProjectCommunication.tenant_id==p.tenant_id,
        ProjectCommunication.project_id==project_id
    ).order_by(ProjectCommunication.occurred_at.desc())).all()

@router.post("/projects/{project_id}/communications",status_code=201)
def create_communication(project_id:str,body:dict,p=Depends(get_principal),db:Session=Depends(get_db)):
    project=project_or_404(db,p.tenant_id,project_id)
    summary=str(body.get("summary") or "").strip()
    if not summary: raise HTTPException(422,"summary_required")
    obj=ProjectCommunication(
        tenant_id=p.tenant_id,project_id=project_id,
        direction=str(body.get("direction") or "internal"),
        channel=str(body.get("channel") or "internal"),
        contact_ref=body.get("contact_ref"),subject=body.get("subject"),
        summary=summary,status=str(body.get("status") or "recorded"),
        approved_version_id=body.get("approved_version_id"),
        external_message_id=body.get("external_message_id"),
        created_by=p.subject
    )
    project.context_version+=1
    db.add(obj);db.commit();db.refresh(obj);return obj


@router.get("/dashboard/today")
def today_dashboard(p=Depends(get_principal),db:Session=Depends(get_db)):
    now=datetime.now(timezone.utc)
    now_cmp=_cmp_dt(now)
    horizon_cmp=now_cmp+timedelta(days=14)
    projects=db.scalars(select(Project).where(
        Project.tenant_id==p.tenant_id
    ).order_by(Project.updated_at.desc())).all()
    project_ids=[x.id for x in projects]

    tasks_rows=db.scalars(select(Task).where(
        Task.tenant_id==p.tenant_id,
        Task.status.notin_(["done","completed"])
    )).all()
    open_decisions=db.scalars(select(ProjectDecision).where(
        ProjectDecision.tenant_id==p.tenant_id,
        ProjectDecision.status=="open"
    ).order_by(ProjectDecision.created_at.desc())).all()
    approvals_rows=db.scalars(select(ApprovalRequest).where(
        ApprovalRequest.tenant_id==p.tenant_id,
        ApprovalRequest.status=="awaiting_approval"
    ).order_by(ApprovalRequest.created_at.desc())).all()
    milestones_rows=db.scalars(select(Milestone).where(
        Milestone.tenant_id==p.tenant_id,
        Milestone.status.notin_(["done","completed"])
    )).all()

    overdue=[
        t for t in tasks_rows
        if t.due_at is not None and _cmp_dt(t.due_at) < now_cmp
    ]
    upcoming_tasks=[
        t for t in tasks_rows
        if t.due_at is not None and now_cmp <= _cmp_dt(t.due_at) <= horizon_cmp
    ]
    upcoming_milestones=[
        m for m in milestones_rows
        if m.due_at is not None and now_cmp <= _cmp_dt(m.due_at) <= horizon_cmp
    ]
    explicit_risk=[x for x in projects if x.status in {"blocked","at_risk"}]
    overdue_project_ids={x.project_id for x in overdue}
    risk_map={x.id:x for x in explicit_risk}
    for project in projects:
        if project.id in overdue_project_ids:
            risk_map[project.id]=project

    return {
        "generated_at":now.isoformat(),
        "tenant_id":p.tenant_id,
        "counts":{
            "projects":len(projects),
            "pending_tasks":len(tasks_rows),
            "overdue_tasks":len(overdue),
            "open_decisions":len(open_decisions),
            "awaiting_approvals":len(approvals_rows),
            "risk_projects":len(risk_map),
        },
        "overdue_tasks":[
            {"id":x.id,"project_id":x.project_id,"title":x.title,"due_at":x.due_at}
            for x in sorted(overdue,key=lambda x:_cmp_dt(x.due_at))[:20]
        ],
        "open_decisions":[
            {"id":x.id,"project_id":x.project_id,"title":x.title,"created_at":x.created_at}
            for x in open_decisions[:20]
        ],
        "awaiting_approvals":[
            {"id":x.id,"project_id":x.project_id,"draft_id":x.draft_id,"created_at":x.created_at}
            for x in approvals_rows[:20]
        ],
        "next_deadlines":sorted(
            [
                {"type":"task","id":x.id,"project_id":x.project_id,"title":x.title,"due_at":x.due_at}
                for x in upcoming_tasks
            ]+
            [
                {"type":"milestone","id":x.id,"project_id":x.project_id,"title":x.title,"due_at":x.due_at}
                for x in upcoming_milestones
            ],
            key=lambda x:_cmp_dt(x["due_at"]),
        )[:30],
        "risk_projects":[
            {"id":x.id,"name":x.name,"status":x.status,"current_stage":x.current_stage}
            for x in risk_map.values()
        ],
    }

@router.get("/projects/{project_id}/providers")
def project_providers(project_id:str,p=Depends(get_principal),db:Session=Depends(get_db)):
    project_or_404(db,p.tenant_id,project_id)
    links=db.scalars(select(ProjectProvider).where(
        ProjectProvider.tenant_id==p.tenant_id,
        ProjectProvider.project_id==project_id
    )).all()
    provider_ids=[x.provider_id for x in links]
    if not provider_ids:
        return []
    providers=db.scalars(select(Provider).where(
        Provider.tenant_id==p.tenant_id,
        Provider.id.in_(provider_ids)
    ).order_by(Provider.name)).all()
    return providers
