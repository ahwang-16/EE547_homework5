"""
Interface tests for Problem 1.

These verify that login and each endpoint answer with the specified keys.
They do not check status codes, headers, or token handling. API_URL
overrides http://localhost:8080.

Run from q1/ with the container running:  pytest test_interfaces.py
"""

import json
import os
import urllib.error
import urllib.request

import pytest

BASE = os.environ.get("API_URL", "http://localhost:8080")
LIST_KEYS = {"arxiv_id", "title", "authors", "published", "categories"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


OPENER = urllib.request.build_opener(NoRedirect)


def call(path, method="GET", token=None, body=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with OPENER.open(req, timeout=5) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


@pytest.fixture(scope="module")
def token():
    try:
        status, _, body = call("/api/login", "POST", body={"username": "admin", "password": "secret"})
    except urllib.error.URLError:
        pytest.fail(f"no server at {BASE}; start the container first")
    reply = json.loads(body)
    assert set(reply) == {"token", "expires_in"}
    return reply["token"]


def test_stats_without_token():
    _, _, body = call("/api/stats")
    reply = json.loads(body)
    assert {"status", "uptime_seconds", "region", "table", "requests"} <= set(reply)
    assert {"total", "by_status"} <= set(reply["requests"])


@pytest.mark.parametrize("path,key", [
    ("/api/papers?category=cs.LG&limit=3", "category"),
    ("/api/papers/author/Yassien%20Shaalan", "author"),
    ("/api/papers/search?category=cs.LG&start=2020-12-01&end=2020-12-31", "start"),
    ("/api/papers/keyword/model", "keyword"),
])
def test_list_shapes(token, path, key):
    _, _, body = call(path, token=token)
    reply = json.loads(body)
    assert key in reply and reply["count"] == len(reply["papers"])
    for p in reply["papers"]:
        assert set(p) == LIST_KEYS


def test_detail(token):
    _, _, body = call("/api/papers?category=cs.LG&limit=1", token=token)
    arxiv_id = json.loads(body)["papers"][0]["arxiv_id"]
    _, _, body = call(f"/api/papers/{arxiv_id}", token=token)
    assert set(json.loads(body)) == LIST_KEYS | {"abstract"}
