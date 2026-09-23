# GLIP API Contract v0.5

Domain:
- GET/POST `/api/v1/clients`
- GET/POST `/api/v1/projects`
- GET `/api/v1/projects/{project_id}`
- GET `/api/v1/projects/{project_id}/cognitive-profile`
- POST `/stages`, `/tasks`, `/milestones`, `/schedule`
- GET `/schedule`
- POST/GET `/budgets` (creation is always draft)
- POST/GET `/knowledge`
- GET `/memory`
- GET `/memory/candidates`
- POST `/memory/candidates/{candidate_id}/promote`

Cognition:
- GET `/projects/{project_id}/context?purpose=...`
- POST `/capabilities/project-summary`
- POST `/capabilities/draft-message`
- POST `/capabilities/risk-scan`
- GET `/projects/{project_id}/executions`

Draft / approval:
- GET `/drafts`
- GET `/drafts/{draft_id}`
- GET `/drafts/{draft_id}/diff`
- POST `/drafts/{draft_id}/versions`
- POST `/drafts/{draft_id}/request-approval`
- POST `/drafts/{draft_id}/approve`
- POST `/drafts/{draft_id}/reject`
- GET `/approved-versions`
- GET `/approvals`

Events:
- GET `/projects/{project_id}/outbox` for controlled inspection.
No publisher worker and no external delivery route are included in v0.5.
