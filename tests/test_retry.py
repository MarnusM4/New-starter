"""Retry helper tests: retries 429/5xx, gives up on 4xx, honours Retry-After."""

import pytest
import requests

from lib.retry import with_retries


def _http_error(status, headers=None):
    resp = requests.Response()
    resp.status_code = status
    if headers:
        resp.headers.update(headers)
    return requests.HTTPError(response=resp)


def test_retries_then_succeeds():
    calls = {"n": 0}

    def call():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _http_error(503)
        return "ok"

    assert with_retries(call, sleep=lambda _: None) == "ok"
    assert calls["n"] == 3


def test_does_not_retry_client_error():
    calls = {"n": 0}

    def call():
        calls["n"] += 1
        raise _http_error(400)

    with pytest.raises(requests.HTTPError):
        with_retries(call, sleep=lambda _: None)
    assert calls["n"] == 1  # no retry on 400


def test_honours_retry_after(monkeypatch):
    slept = []

    def call():
        raise _http_error(429, {"Retry-After": "7"})

    with pytest.raises(requests.HTTPError):
        with_retries(call, max_attempts=2, sleep=slept.append)
    assert slept == [7.0]
