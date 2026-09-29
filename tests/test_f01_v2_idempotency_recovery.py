
from sqlalchemy import func, select

from glip.models import Project, ProjectCreateIdempotency


def test_project_idempotency_integrityerror_recovers_winner_without_orphan(
    client, auth_a, db, monkeypatch
):
    key = "f01-v2-integrity-recovery"
    body = {"name": "F01 V2 recovery branch"}
    headers = dict(auth_a)
    headers["Idempotency-Key"] = key

    first = client.post("/api/v1/projects", headers=headers, json=body)
    assert first.status_code == 201, first.text
    winner = first.json()

    original_scalar = db.scalar
    hidden = {"done": False}

    def scalar_with_one_hidden_idempotency_read(statement, *args, **kwargs):
        sql = str(statement).lower()
        if not hidden["done"] and "project_create_idempotency" in sql:
            hidden["done"] = True
            return None
        return original_scalar(statement, *args, **kwargs)

    monkeypatch.setattr(db, "scalar", scalar_with_one_hidden_idempotency_read)

    second = client.post("/api/v1/projects", headers=headers, json=body)

    assert hidden["done"] is True, "the preflight idempotency read was not exercised"
    assert second.status_code in (200, 201), second.text
    assert second.json()["id"] == winner["id"]

    project_count = original_scalar(
        select(func.count())
        .select_from(Project)
        .where(
            Project.tenant_id == "tenant-a",
            Project.name == body["name"],
        )
    )
    idempotency_count = original_scalar(
        select(func.count())
        .select_from(ProjectCreateIdempotency)
        .where(
            ProjectCreateIdempotency.tenant_id == "tenant-a",
            ProjectCreateIdempotency.idempotency_key == key,
        )
    )

    assert project_count == 1
    assert idempotency_count == 1
