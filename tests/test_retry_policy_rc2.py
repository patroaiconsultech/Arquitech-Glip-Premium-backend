from __future__ import annotations

import pytest

from glip.integrations.orkio.retry_policy import (
    HttpFailureClass,
    classify_http_failure,
)


@pytest.mark.parametrize("status", [401,403])
def test_auth_statuses_are_terminal(status):
    assert classify_http_failure(status) is HttpFailureClass.AUTH_TERMINAL


@pytest.mark.parametrize("status", [400,404,409,410,412,415,422])
def test_contract_statuses_are_terminal(status):
    assert classify_http_failure(status) is HttpFailureClass.CONTRACT_TERMINAL


@pytest.mark.parametrize("status", [408,429,502,503,504])
def test_transient_statuses_are_the_only_retryable_set(status):
    assert classify_http_failure(status) is HttpFailureClass.RETRYABLE_TRANSIENT


@pytest.mark.parametrize("status", [405,406,418,500,501,505,599])
def test_unknown_or_other_failures_default_terminal(status):
    assert classify_http_failure(status) is HttpFailureClass.UPSTREAM_TERMINAL
