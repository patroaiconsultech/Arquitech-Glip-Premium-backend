from __future__ import annotations

import hashlib
import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from glip.artifacts.service import render_and_validate, artifact_capability_manifest
from glip.architecture import detect_ifc_schema, architecture_capability_manifest
from glip.config import Settings
from glip.models import ArtifactAsset, ArtifactUsageEvent, ArchitecturalSource

@pytest.mark.parametrize("fmt,magic",[
    ("docx",b"PK"),
    ("pdf",b"%PDF"),
    ("pptx",b"PK"),
    ("xlsx",b"PK"),
])
def test_document_renderers_are_real_and_validated(fmt,magic):
    content="# Projeto GLIP\n\n## Escopo\n\n- Arquitetura\n- Compatibilização\n\n| Item | Status |\n|---|---|\n| Planta | Aprovada |"
    result=render_and_validate(format=fmt,content=content,filename=f"projeto.{fmt}")
    assert result.data.startswith(magic)
    assert result.sha256==hashlib.sha256(result.data).hexdigest()
    assert result.semantic_text.strip()
    assert result.renderer.startswith("glip_")

def test_artifact_manifest_is_glip_scoped_and_image_is_not_faked():
    s=SimpleNamespace(artifacts_enabled=True,artifact_provider_profile_ref="glip-local")
    m=artifact_capability_manifest(s)
    assert m["billing_scope"]=="glip"
    assert m["formats"]["docx"]["supported"] is True
    assert m["formats"]["pptx"]["supported"] is True
    assert m["formats"]["image"]["supported"] is False

def test_ifc_schema_detection_preserves_bim_semantics():
    prefix=b"ISO-10303-21;HEADER;FILE_SCHEMA(('IFC4X3_ADD2'));ENDSEC;"
    assert detect_ifc_schema(prefix)=="IFC4X3_ADD2"

def test_architecture_manifest_makes_ifc_first_class():
    s=SimpleNamespace(architecture_uploads_enabled=False)
    m=architecture_capability_manifest(s)
    assert m["bim"]["ifc_first_class"] is True
    assert m["scene"]["distribution_format"]=="glb/gltf"
    assert m["render"]["status"]=="PENDING_GATE_4"

def test_production_artifacts_cannot_use_local_storage():
    with pytest.raises(ValueError,match="artifact_s3_required_outside_dev"):
        Settings(
            environment="production",
            database_url="postgresql+psycopg://u:p@db/glip",
            cors_origins="https://glip.example",
            require_migration_head=True,
            auth_mode="native_session",
            auth_session_secret="s"*40,
            auth_password_pepper="p"*40,
            orkio_mode="disabled",
            artifacts_enabled=True,
            artifact_storage_backend="local",
        )

def test_artifact_profile_must_be_glip_scoped():
    with pytest.raises(ValueError,match="artifact_provider_profile_must_be_glip_scoped"):
        Settings(
            environment="test",
            auth_mode="dev_headers",
            orkio_mode="disabled",
            artifacts_enabled=True,
            artifact_provider_profile_ref="efata-default",
        )
