from __future__ import annotations

from enum import Enum


class HttpFailureClass(str, Enum):
    AUTH_TERMINAL = "AUTH_TERMINAL"
    CONTRACT_TERMINAL = "CONTRACT_TERMINAL"
    RETRYABLE_TRANSIENT = "RETRYABLE_TRANSIENT"
    UPSTREAM_TERMINAL = "UPSTREAM_TERMINAL"


AUTH_TERMINAL_STATUSES = frozenset({401, 403})
CONTRACT_TERMINAL_STATUSES = frozenset({400, 404, 409, 410, 412, 415, 422})
RETRYABLE_TRANSIENT_STATUSES = frozenset({408, 429, 502, 503, 504})


def classify_http_failure(status_code: int) -> HttpFailureClass:
    """Classify an HTTP failure before retry logic is entered.

    The default is terminal. New status codes therefore fail closed instead of
    silently becoming retryable.
    """
    if status_code in AUTH_TERMINAL_STATUSES:
        return HttpFailureClass.AUTH_TERMINAL
    if status_code in CONTRACT_TERMINAL_STATUSES:
        return HttpFailureClass.CONTRACT_TERMINAL
    if status_code in RETRYABLE_TRANSIENT_STATUSES:
        return HttpFailureClass.RETRYABLE_TRANSIENT
    return HttpFailureClass.UPSTREAM_TERMINAL
