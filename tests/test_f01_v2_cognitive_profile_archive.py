
from sqlalchemy import select

from glip.models import ProjectCognitiveProfile


def _create_project(client, auth_a, name: str, key: str):
    headers = dict(auth_a)
    headers["Idempotency-Key"] = key
    response = client.post("/api/v1/projects", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _profile(db, project_id: str):
    return db.scalar(
        select(ProjectCognitiveProfile).where(
            ProjectCognitiveProfile.tenant_id == "tenant-a",
            ProjectCognitiveProfile.project_id == project_id,
        )
    )


def test_archived_project_missing_profile_does_not_lazy_create(client, auth_a, db):
    project = _create_project(client, auth_a, "F01 V2 cognitive missing", "f01-v2-cognitive-missing")
    profile = _profile(db, project["id"])
    assert profile is not None
    db.delete(profile)
    db.commit()
    assert _profile(db, project["id"]) is None

    archived = client.post(f"/api/v1/projects/{project['id']}/archive", headers=auth_a)
    assert archived.status_code == 200, archived.text

    response = client.get(f"/api/v1/projects/{project['id']}/cognitive-profile", headers=auth_a)
    assert response.status_code == 404, response.text
    assert response.json().get("detail") == "cognitive_profile_not_found"
    assert _profile(db, project["id"]) is None


def test_archived_project_existing_profile_remains_readable(client, auth_a, db):
    project = _create_project(client, auth_a, "F01 V2 cognitive existing", "f01-v2-cognitive-existing")
    assert _profile(db, project["id"]) is not None

    archived = client.post(f"/api/v1/projects/{project['id']}/archive", headers=auth_a)
    assert archived.status_code == 200, archived.text

    response = client.get(f"/api/v1/projects/{project['id']}/cognitive-profile", headers=auth_a)
    assert response.status_code == 200, response.text
    assert response.json()["project_id"] == project["id"]
