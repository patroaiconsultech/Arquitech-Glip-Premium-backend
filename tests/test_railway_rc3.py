from pathlib import Path
import pytest
from glip.config import Settings

ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize("url,prefix",[
    ("postgres://u:p@db:5432/glip","postgresql+psycopg://"),
    ("postgresql://u:p@db:5432/glip","postgresql+psycopg://"),
])
def test_railway_postgres_url_is_normalized_to_psycopg3(url,prefix):
    s=Settings(environment="test",database_url=url,auth_mode="dev_headers",orkio_mode="disabled")
    assert s.database_url.startswith(prefix)

def native_settings(**overrides):
    data={
        "environment":"test","database_url":"sqlite://","auth_mode":"native_session",
        "auth_session_secret":"s"*40,"auth_password_pepper":"p"*40,"orkio_mode":"disabled",
    }
    data.update(overrides)
    return Settings(**data)

def test_native_session_configuration_is_accepted():
    assert native_settings().auth_mode=="native_session"

def test_native_session_secret_must_be_long():
    with pytest.raises(ValueError,match="auth_session_secret_too_short"):
        native_settings(auth_session_secret="short")

def test_native_password_pepper_must_be_long():
    with pytest.raises(ValueError,match="auth_password_pepper_too_short"):
        native_settings(auth_password_pepper="short")

def test_native_idle_ttl_cannot_exceed_absolute_ttl():
    with pytest.raises(ValueError,match="auth_idle_ttl_invalid"):
        native_settings(auth_session_ttl_seconds=1800,auth_idle_ttl_seconds=3600)

def test_readiness_returns_503_when_core_is_not_ready(client,monkeypatch):
    import glip.main as main
    monkeypatch.setattr(main,"database_readiness",lambda *a,**k:{
        "database_connect":False,"database_driver":None,"migration_current":None,
        "migration_head":None,"migration_expected":"0005_glip_artifact_bim_foundation",
    })
    r=client.get("/health/ready")
    assert r.status_code==503
    assert r.json()["status"]=="not_ready"

def test_readiness_returns_200_when_core_is_ready(client,monkeypatch):
    import glip.main as main
    monkeypatch.setattr(main,"database_readiness",lambda *a,**k:{
        "database_connect":True,"database_driver":"sqlite","migration_current":None,
        "migration_head":None,"migration_expected":"0005_glip_artifact_bim_foundation",
    })
    r=client.get("/health/ready")
    assert r.status_code==200
    assert r.json()["status"]=="ready"

def test_docker_uses_railway_port_and_public_bind():
    docker=(ROOT/"Dockerfile").read_text()
    assert "--host 0.0.0.0" in docker
    assert "${PORT:-8080}" in docker

def test_runtime_lock_contains_expected_pins():
    lines=[x for x in (ROOT/"requirements.lock.txt").read_text().splitlines() if x.strip() and not x.startswith("#")]
    assert len(lines)>=25
    assert any(x.startswith("psycopg==") for x in lines)
    assert any(x.startswith("psycopg-binary==") for x in lines)

def test_bootstrap_is_explicit_and_has_no_account_linking():
    source=(ROOT/"scripts/bootstrap_membership.py").read_text()
    assert 'GLIP_BOOTSTRAP_CONFIRM' in source
    assert '!="YES"' in source
    assert "credential already exists" in source
    assert "oidc" not in source.lower()



def test_native_lockout_bounds_are_validated():
    with pytest.raises(ValueError,match="auth_max_failed_attempts_invalid"):
        native_settings(auth_max_failed_attempts=2)
    with pytest.raises(ValueError,match="auth_lockout_seconds_invalid"):
        native_settings(auth_lockout_seconds=30)
