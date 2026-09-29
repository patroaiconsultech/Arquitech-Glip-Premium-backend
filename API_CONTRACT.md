# GLIP API Contract v0.6 — F01 Project Lifecycle

Domain:
- GET/POST `/api/v1/clients`
- GET `/api/v1/projects` — active projects by default; `?archived=true` lists archived projects.
- POST `/api/v1/projects` — requires `Idempotency-Key`; tenant/actor scoped durable replay protection.
- GET `/api/v1/projects/{project_id}`
- PATCH `/api/v1/projects/{project_id}` — capability `project.update`.
- POST `/api/v1/projects/{project_id}/archive` — capability `project.archive`.
- POST `/api/v1/projects/{project_id}/restore` — capability `project.restore`.
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
No publisher worker and no external delivery route are included in v0.6.


## F01 mutation authorization

Effective project capabilities are returned by `GET /api/v1/me`.

- `owner`, `admin`: create, update, archive, restore.
- `architect`, `member`: create, update.
- unknown/external roles: no project mutation capability by default.

All project lookups remain tenant-scoped. Cross-tenant mutation attempts resolve as not found.
