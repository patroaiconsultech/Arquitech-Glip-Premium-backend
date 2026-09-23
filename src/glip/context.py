from uuid import uuid4
from datetime import datetime, timezone
from fastapi import HTTPException
from sqlalchemy import select
from .models import (
    Project, Client, Task, Document, Milestone, ProjectStage, ProjectCognitiveProfile,
    ProjectKnowledgeItem, ProjectMemoryFact, ScheduleItem
)

def project_or_404(db, tenant_id: str, project_id: str) -> Project:
    project = db.scalar(select(Project).where(Project.id==project_id, Project.tenant_id==tenant_id))
    if not project:
        raise HTTPException(404,"project_not_found")
    return project

def _purpose_allowed(allowed: list, purpose: str) -> bool:
    return not allowed or purpose in allowed or "*" in allowed

def build(db, tenant_id: str, project_id: str, actor_id: str, correlation_id: str, purpose: str="general") -> dict:
    project = project_or_404(db,tenant_id,project_id)
    profile = db.scalar(select(ProjectCognitiveProfile).where(
        ProjectCognitiveProfile.tenant_id==tenant_id,
        ProjectCognitiveProfile.project_id==project_id
    ))
    client = db.scalar(select(Client).where(Client.id==project.client_id,Client.tenant_id==tenant_id)) if project.client_id else None
    tasks = db.scalars(select(Task).where(Task.tenant_id==tenant_id,Task.project_id==project_id)).all()
    docs = db.scalars(select(Document).where(
        Document.tenant_id==tenant_id,Document.project_id==project_id,Document.active.is_(True)
    )).all()
    milestones = db.scalars(select(Milestone).where(Milestone.tenant_id==tenant_id,Milestone.project_id==project_id)).all()
    stages = db.scalars(select(ProjectStage).where(
        ProjectStage.tenant_id==tenant_id,ProjectStage.project_id==project_id
    ).order_by(ProjectStage.sequence)).all()
    schedule = db.scalars(select(ScheduleItem).where(
        ScheduleItem.tenant_id==tenant_id,ScheduleItem.project_id==project_id
    )).all()

    now = datetime.now(timezone.utc)
    knowledge = db.scalars(select(ProjectKnowledgeItem).where(
        ProjectKnowledgeItem.tenant_id==tenant_id,
        ProjectKnowledgeItem.project_id==project_id,
        ProjectKnowledgeItem.status=="active",
    )).all()
    knowledge = [
        k for k in knowledge
        if (k.expires_at is None or k.expires_at > now) and _purpose_allowed(k.allowed_purposes,purpose)
    ]
    memory = db.scalars(select(ProjectMemoryFact).where(
        ProjectMemoryFact.tenant_id==tenant_id,
        ProjectMemoryFact.project_id==project_id,
        ProjectMemoryFact.status=="active",
    )).all()

    authorized_sources = []
    for d in docs:
        if _purpose_allowed(d.allowed_purposes,purpose):
            authorized_sources.append({
                "source_ref":f"glip-doc:{d.id}:v{d.version}",
                "source_type":"document",
                "source_id":d.id,
                "version":d.version,
                "classification":d.classification,
                "allowed_purposes":d.allowed_purposes,
            })
    for k in knowledge:
        authorized_sources.append({
            "source_ref":f"glip-knowledge:{k.id}:v{k.version}",
            "source_type":"knowledge",
            "source_id":k.id,
            "version":k.version,
            "classification":k.classification,
            "allowed_purposes":k.allowed_purposes,
        })

    return {
        "schema_version":"glip.project-context.v2",
        "context_id":str(uuid4()),
        "context_version":project.context_version,
        "tenant_id":tenant_id,
        "organization_id":tenant_id,
        "project_id":project_id,
        "purpose":purpose,
        "actor":{"user_id":actor_id,"roles":[]},
        "project":{"name":project.name,"stage":project.current_stage,"status":project.status},
        "client":{"client_ref":client.id,"name":client.name} if client else None,
        "cognitive_profile":{
            "profile_id":profile.id if profile else None,
            "baseline_id":profile.baseline_id if profile else None,
            "baseline_version":profile.baseline_version if profile else None,
            "policy_profile_id":profile.policy_profile_id if profile else None,
            "voice_profile_id":profile.voice_profile_id if profile else None,
            "memory_namespace":profile.memory_namespace if profile else None,
        },
        "authorized_sources":authorized_sources,
        "knowledge":[{"knowledge_key":k.knowledge_key,"summary":k.summary,"source_ref":f"glip-knowledge:{k.id}:v{k.version}"} for k in knowledge],
        "memory":[{"fact_key":m.fact_key,"fact_value":m.fact_value,"version":m.version,"source_approved_version_id":m.source_approved_version_id} for m in memory],
        "tasks":[{"id":t.id,"title":t.title,"status":t.status,"due_at":t.due_at.isoformat() if t.due_at else None} for t in tasks],
        "milestones":[{"id":m.id,"title":m.title,"status":m.status,"due_at":m.due_at.isoformat() if m.due_at else None} for m in milestones],
        "stages":[{"id":s.id,"name":s.name,"status":s.status,"sequence":s.sequence} for s in stages],
        "schedule":[{"id":x.id,"title":x.title,"status":x.status,"starts_at":x.starts_at.isoformat() if x.starts_at else None,"ends_at":x.ends_at.isoformat() if x.ends_at else None} for x in schedule],
        "constraints":["minimum_necessary_data","tenant_project_scope","no_external_write"],
        "source_refs":[x["source_ref"] for x in authorized_sources],
        "correlation_id":correlation_id,
    }
