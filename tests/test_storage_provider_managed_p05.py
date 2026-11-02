"""Contract tests for Railway Buckets, whose S3 API does not support SSE headers."""
from pathlib import Path

import pytest

from glip.config import Settings
from glip.artifacts.storage import S3BlobStorage


class _MissingObject(Exception):
    response = {"Error": {"Code": "404"}}


class _FakeS3:
    def __init__(self):
        self.put = None
        self.multipart = None

    def head_object(self, **kwargs):
        raise _MissingObject()

    def put_object(self, **kwargs):
        self.put = kwargs

    def upload_fileobj(self, source, bucket, key, ExtraArgs):
        self.multipart = (source.read(), bucket, key, ExtraArgs)


def _storage(mode: str):
    return S3BlobStorage(
        bucket="test-private-bucket",
        region="auto",
        endpoint_url="https://t3.storageapi.dev",
        access_key_id="test",
        secret_access_key="test",
        prefix="glip-staging",
        server_side_encryption=mode,
        kms_key_id="",
    )


@pytest.mark.parametrize("mode,should_have_sse", [
    ("provider_managed", False),
    ("AES256", True),
])
def test_put_s3_encryption_header_is_explicit(monkeypatch, mode, should_have_sse):
    fake = _FakeS3()
    monkeypatch.setattr(S3BlobStorage, "_client", lambda _self: fake)
    assert _storage(mode).put_if_absent("test-asset", b"hello", content_type="text/plain")
    assert ("ServerSideEncryption" in fake.put) is should_have_sse
    assert fake.put["Key"] == "glip-staging/test-asset"


def test_multipart_omits_unsupported_header(monkeypatch, tmp_path: Path):
    fake = _FakeS3()
    monkeypatch.setattr(S3BlobStorage, "_client", lambda _self: fake)
    source = tmp_path / "file.txt"
    source.write_bytes(b"upload")
    assert _storage("provider_managed").put_file_if_absent(
        "large-test-asset", source, content_type="text/plain"
    )
    assert fake.multipart[0] == b"upload"
    assert "ServerSideEncryption" not in fake.multipart[-1]


def test_provider_managed_only_for_https_railway_bucket_endpoint():
    valid = Settings(
        _env_file=None, environment="test",
        artifact_storage_sse="provider_managed",
        artifact_storage_endpoint_url="https://t3.storageapi.dev",
    )
    assert valid.artifact_storage_sse == "provider_managed"
    for endpoint in (
        None,
        "http://t3.storageapi.dev",
        "https://storageapi.dev.attacker.example",
        "https://s3.amazonaws.com",
        "https://storageapi.dev",
        "https://attacker@t3.storageapi.dev",
    ):
        with pytest.raises(ValueError, match="provider_managed_requires_railway_bucket_endpoint"):
            Settings(
                _env_file=None, environment="test",
                artifact_storage_sse="provider_managed",
                artifact_storage_endpoint_url=endpoint,
            )
