from functools import lru_cache
from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="GLIP_", env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str = "sqlite:///./glip.db"
    cors_origins: str = "http://localhost:5174"

    # Human authentication belongs to GLIP. Production target is native_session.
    auth_mode: str = "dev_headers"  # dev_headers | native_session
    auth_session_cookie_name: str = "glip_session"
    auth_session_secret: str = ""
    auth_password_pepper: str = ""
    auth_session_ttl_seconds: int = 28800
    auth_idle_ttl_seconds: int = 1800
    auth_session_touch_interval_seconds: int = 300
    auth_password_min_length: int = 12
    auth_password_max_length: int = 256
    auth_scrypt_n: int = 16384
    auth_scrypt_r: int = 8
    auth_scrypt_p: int = 1
    auth_max_failed_attempts: int = 8
    auth_lockout_seconds: int = 900

    # ORKIO/Efatà is optional intelligence, never the GLIP system of record.
    orkio_mode: str = "disabled"
    orkio_base_url: str = ""
    orkio_probe_timeout_seconds: float = 5.0
    orkio_timeout_seconds: float = 20.0
    orkio_max_attempts: int = 2
    orkio_retry_backoff_seconds: float = 0.25
    orkio_circuit_failure_threshold: int = 4
    orkio_circuit_cooldown_seconds: float = 20.0
    orkio_execution_lease_seconds: int = 90
    orkio_m2m_token: str = ""
    orkio_capability_execute_path: str = ""
    orkio_capability_contract_version: str = "ORKIO-CAPABILITY-REQUEST-1"
    orkio_response_contract_version: str = "ORKIO-RESPONSE-1"


    # GLIP-owned artifact/document runtime. Reuses proven renderer patterns but
    # never shares Efata provider credentials, billing scope or storage namespace.
    artifacts_enabled: bool = False
    artifact_storage_backend: str = "local"  # local | s3
    artifact_storage_path: str = "./data/glip-artifacts"
    artifact_storage_bucket: str = ""
    artifact_storage_region: str = "us-east-1"
    artifact_storage_endpoint_url: str | None = None
    artifact_storage_access_key_id: str = ""
    artifact_storage_secret_access_key: str = ""
    artifact_storage_sse: str = "AES256"  # AES256 | aws:kms
    artifact_storage_kms_key_id: str = ""
    artifact_storage_prefix: str = "glip"
    artifact_provider_profile_ref: str = "glip-local"
    max_artifact_bytes: int = 50_000_000

    # Architectural source foundation. IFC is first-class and remains the
    # semantic source of truth; GLB/glTF is a derived distribution/render format.
    architecture_uploads_enabled: bool = False
    max_architectural_source_bytes: int = 250_000_000

    # BIM semantic ingestion runs in an isolated worker. The API only queues jobs.
    bim_semantic_enabled: bool = False
    bim_semantic_engine: str = "ifcopenshell"
    bim_semantic_max_elements: int = 100_000
    bim_job_lease_seconds: int = 300

    # CAD semantic ingestion is isolated in a worker. DXF is parsed directly;
    # DWG remains an Autodesk/ODA adapter concern and is not decoded in-process.
    cad_semantic_enabled: bool = False
    cad_semantic_engine: str = "ezdxf"
    cad_semantic_max_entities: int = 100_000
    cad_job_lease_seconds: int = 300

    # Deterministic GLB preview generation. This produces source linework
    # previews only and must never be presented as inferred architectural 3D.
    geometry_build_enabled: bool = False
    geometry_preview_engine: str = "trimesh"
    geometry_preview_max_paths: int = 20_000
    geometry_preview_max_points: int = 500_000
    geometry_job_lease_seconds: int = 300

    # Pricing Intelligence is a separate future plane. Quantity extraction can
    # be enabled independently; authoritative market-price ingestion is not yet.
    pricing_intelligence_enabled: bool = False

    realtime_mode: str = "pending_external"
    voice_mode: str = "pending_external"
    avatar_mode: str = "pending_external"

    release_id: str = "local"
    deployment_id: str = ""
    replica_id: str = ""
    require_migration_head: bool = False
    default_project_baseline_id: str = "glip.architecture.core"
    default_project_baseline_version: str = "1.0.0"
    default_project_policy_id: str = "glip.project.policy.v1"
    default_voice_profile_id: str = "pending_external"

    @property
    def cors_list(self) -> list[str]:
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    @model_validator(mode="after")
    def validate_modes(self):
        if self.database_url.startswith("postgres://"):
            self.database_url="postgresql+psycopg://"+self.database_url[len("postgres://"):]
        elif self.database_url.startswith("postgresql://"):
            self.database_url="postgresql+psycopg://"+self.database_url[len("postgresql://"):]

        if self.environment in {"staging","production"}:
            if not self.database_url.startswith("postgresql"):
                raise ValueError("postgresql_required_outside_dev")
            if not self.require_migration_head:
                raise ValueError("migration_head_check_required_outside_dev")
            if "*" in self.cors_list:
                raise ValueError("cors_wildcard_forbidden")
            if self.environment=="production":
                if any(origin.startswith("http://") for origin in self.cors_list):
                    raise ValueError("production_cors_https_required")
                if any("localhost" in origin or "127.0.0.1" in origin for origin in self.cors_list):
                    raise ValueError("production_cors_localhost_forbidden")

        if self.auth_mode not in {"dev_headers","native_session"}:
            raise ValueError("unsupported_auth_mode")
        if self.environment not in {"development","test"} and self.auth_mode=="dev_headers":
            raise ValueError("dev_headers_forbidden_outside_dev")
        if self.auth_mode=="native_session":
            if len(self.auth_session_secret)<32:
                raise ValueError("auth_session_secret_too_short")
            if len(self.auth_password_pepper)<32:
                raise ValueError("auth_password_pepper_too_short")
            if not (900 <= self.auth_session_ttl_seconds <= 86400):
                raise ValueError("auth_session_ttl_invalid")
            if not (300 <= self.auth_idle_ttl_seconds <= self.auth_session_ttl_seconds):
                raise ValueError("auth_idle_ttl_invalid")
            if not (30 <= self.auth_session_touch_interval_seconds <= self.auth_idle_ttl_seconds):
                raise ValueError("auth_session_touch_interval_invalid")
            if self.auth_password_min_length < 12:
                raise ValueError("auth_password_min_length_too_short")
            if self.auth_password_max_length < self.auth_password_min_length:
                raise ValueError("auth_password_length_range_invalid")
            if self.auth_scrypt_n < 16384 or self.auth_scrypt_r < 8 or self.auth_scrypt_p < 1:
                raise ValueError("auth_scrypt_cost_too_low")
            if self.auth_max_failed_attempts < 3 or self.auth_max_failed_attempts > 20:
                raise ValueError("auth_max_failed_attempts_invalid")
            if self.auth_lockout_seconds < 60 or self.auth_lockout_seconds > 86400:
                raise ValueError("auth_lockout_seconds_invalid")

        if self.orkio_mode not in {"disabled","probe","capability_v1","mock"}:
            raise ValueError("unsupported_orkio_mode")
        if self.orkio_mode=="mock" and self.environment not in {"development","test"}:
            raise ValueError("orkio_mock_forbidden_outside_dev")
        if self.orkio_mode in {"probe","capability_v1"} and not self.orkio_base_url.strip():
            raise ValueError("orkio_base_url_required")
        if self.orkio_mode=="capability_v1":
            if not self.orkio_m2m_token.strip():
                raise ValueError("orkio_m2m_token_required")
            if not self.orkio_capability_execute_path.strip():
                raise ValueError("orkio_capability_execute_path_required")
        if self.orkio_probe_timeout_seconds <= 0 or self.orkio_probe_timeout_seconds > 10:
            raise ValueError("orkio_probe_timeout_invalid")
        if self.orkio_timeout_seconds <= 0 or self.orkio_timeout_seconds > 60:
            raise ValueError("orkio_timeout_invalid")
        if self.orkio_max_attempts < 1 or self.orkio_max_attempts > 3:
            raise ValueError("orkio_max_attempts_invalid")
        minimum_lease=int(
            self.orkio_timeout_seconds*self.orkio_max_attempts
            + self.orkio_retry_backoff_seconds*max(0,self.orkio_max_attempts-1)
            + 10
        )
        if self.orkio_execution_lease_seconds < minimum_lease:
            raise ValueError("orkio_execution_lease_too_short")
        if self.orkio_execution_lease_seconds > 600:
            raise ValueError("orkio_execution_lease_too_long")


        if self.artifact_storage_backend not in {"local","s3"}:
            raise ValueError("artifact_storage_backend_invalid")
        if self.artifact_storage_sse not in {"AES256","aws:kms"}:
            raise ValueError("artifact_storage_sse_invalid")
        if self.max_artifact_bytes < 1_000_000 or self.max_artifact_bytes > 500_000_000:
            raise ValueError("max_artifact_bytes_invalid")
        if self.max_architectural_source_bytes < 10_000_000 or self.max_architectural_source_bytes > 2_000_000_000:
            raise ValueError("max_architectural_source_bytes_invalid")
        if self.bim_semantic_engine not in {"ifcopenshell"}:
            raise ValueError("bim_semantic_engine_invalid")
        if self.bim_semantic_max_elements < 100 or self.bim_semantic_max_elements > 1_000_000:
            raise ValueError("bim_semantic_max_elements_invalid")
        if self.bim_job_lease_seconds < 60 or self.bim_job_lease_seconds > 3600:
            raise ValueError("bim_job_lease_seconds_invalid")
        if self.bim_semantic_enabled and not self.architecture_uploads_enabled:
            raise ValueError("bim_semantic_requires_architecture_uploads")
        if self.cad_semantic_engine not in {"ezdxf"}:
            raise ValueError("cad_semantic_engine_invalid")
        if self.cad_semantic_max_entities < 100 or self.cad_semantic_max_entities > 1_000_000:
            raise ValueError("cad_semantic_max_entities_invalid")
        if self.cad_job_lease_seconds < 60 or self.cad_job_lease_seconds > 3600:
            raise ValueError("cad_job_lease_seconds_invalid")
        if self.cad_semantic_enabled and not self.architecture_uploads_enabled:
            raise ValueError("cad_semantic_requires_architecture_uploads")
        if self.geometry_preview_engine not in {"trimesh"}:
            raise ValueError("geometry_preview_engine_invalid")
        if self.geometry_preview_max_paths < 100 or self.geometry_preview_max_paths > 100_000:
            raise ValueError("geometry_preview_max_paths_invalid")
        if self.geometry_preview_max_points < 1_000 or self.geometry_preview_max_points > 5_000_000:
            raise ValueError("geometry_preview_max_points_invalid")
        if self.geometry_job_lease_seconds < 60 or self.geometry_job_lease_seconds > 3600:
            raise ValueError("geometry_job_lease_seconds_invalid")
        if self.geometry_build_enabled and not self.architecture_uploads_enabled:
            raise ValueError("geometry_build_requires_architecture_uploads")
        artifact_or_arch_enabled = (
            self.artifacts_enabled or self.architecture_uploads_enabled or self.bim_semantic_enabled
            or self.cad_semantic_enabled or self.geometry_build_enabled
        )
        if artifact_or_arch_enabled:
            if not self.artifact_provider_profile_ref.strip().lower().startswith("glip"):
                raise ValueError("artifact_provider_profile_must_be_glip_scoped")
        if self.environment in {"staging","production"} and artifact_or_arch_enabled:
            if self.artifact_storage_backend != "s3":
                raise ValueError("artifact_s3_required_outside_dev")
            if not self.artifact_storage_bucket.strip():
                raise ValueError("artifact_storage_bucket_required")
            if not self.artifact_storage_access_key_id.strip() or not self.artifact_storage_secret_access_key.strip():
                raise ValueError("artifact_storage_credentials_required")
            if not self.artifact_storage_prefix.strip().lower().startswith("glip"):
                raise ValueError("artifact_storage_prefix_must_be_glip_scoped")
            if self.artifact_storage_sse=="aws:kms" and not self.artifact_storage_kms_key_id.strip():
                raise ValueError("artifact_storage_kms_key_required")

        allowed={"disabled","pending_external","enabled"}
        for name,value in {
            "realtime_mode":self.realtime_mode,
            "voice_mode":self.voice_mode,
            "avatar_mode":self.avatar_mode,
        }.items():
            if value not in allowed:
                raise ValueError(f"{name}_invalid")
        return self

@lru_cache
def get_settings() -> Settings:
    return Settings()

settings=get_settings()
