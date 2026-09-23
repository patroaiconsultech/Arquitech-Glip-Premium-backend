import pytest
from glip.config import Settings


def test_execution_lease_must_cover_retry_window():
    with pytest.raises(ValueError,match="orkio_execution_lease_too_short"):
        Settings(
            environment="test",
            database_url="sqlite://",
            auth_mode="dev_headers",
            orkio_mode="disabled",
            orkio_timeout_seconds=20,
            orkio_max_attempts=2,
            orkio_retry_backoff_seconds=0.25,
            orkio_execution_lease_seconds=20,
        )


def test_default_execution_lease_is_valid():
    s=Settings(
        environment="test",
        database_url="sqlite://",
        auth_mode="dev_headers",
        orkio_mode="disabled",
    )
    assert s.orkio_execution_lease_seconds==90
