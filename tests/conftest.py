import os
os.environ["GLIP_ENVIRONMENT"]="test";os.environ["GLIP_DATABASE_URL"]="sqlite://";os.environ["GLIP_AUTH_MODE"]="dev_headers";os.environ["GLIP_ORKIO_MODE"]="mock"
import pytest
from uuid import uuid4
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient
from glip.orm import Base
from glip.database import get_db
from glip.main import app
from glip.models import Tenant,Membership
@pytest.fixture()
def db():
    e=create_engine("sqlite://",connect_args={"check_same_thread":False},poolclass=StaticPool);Base.metadata.create_all(e);S=sessionmaker(bind=e,expire_on_commit=False)
    with S() as s: yield s
@pytest.fixture()
def client(db):
    def override_db():
        yield db
    app.dependency_overrides[get_db]=override_db
    test_client=TestClient(app)
    original_post=test_client.post

    def post(url,*args,**kwargs):
        if url=="/api/v1/projects":
            h=dict(kwargs.get("headers") or {})
            h.setdefault("Idempotency-Key",str(uuid4()))
            kwargs["headers"]=h
        return original_post(url,*args,**kwargs)

    test_client.post=post
    yield test_client
    app.dependency_overrides.clear()
def provision(db,t,u):
    db.add(Tenant(id=t,name=t));db.add(Membership(tenant_id=t,external_subject=u,display_name=u,role="owner",active=True));db.commit()
@pytest.fixture()
def auth_a(db): provision(db,"tenant-a","user-a");return {"X-GLIP-Tenant-ID":"tenant-a","X-GLIP-User-ID":"user-a"}
@pytest.fixture()
def auth_b(db): provision(db,"tenant-b","user-b");return {"X-GLIP-Tenant-ID":"tenant-b","X-GLIP-User-ID":"user-b"}
