"""Pilot workflow controls exercise the request boundary without production access."""

from __future__ import annotations

import urllib.request
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from io import BytesIO
from pathlib import Path
from uuid import UUID

import pytest

from loremfile.config import VERIFY_USER_AGENT
from loremfile.infra import mcp_worker, usage
from loremfile.infra.cloudflare_api import Client, CloudflareError, Multipart, Response

ROOT = Path(__file__).resolve().parents[2]
ZONE = "/zones/zone"
ROUTES = f"{ZONE}/workers/routes"
SCRIPT = "/accounts/account/workers/scripts/loremfile-mcp"


@pytest.fixture
def cloudflare(monkeypatch):
    calls = []
    routes = [{"pattern": "elsewhere.example/*", "script": "another-worker", "id": "other"}]
    client = Client("fake", "zone", "account")

    def send(method, path, payload):
        calls.append((method, path, payload))
        if method == "GET" and path == ZONE:
            return Response(200, {"result": {"name": "loremfile.dev"}})
        if method == "GET" and path == ROUTES:
            return Response(200, {"result": routes.copy()})
        if method == "POST" and path == ROUTES:
            routes.append({**payload, "id": "pilot"})
        if method == "DELETE" and path == f"{ROUTES}/pilot":
            routes.pop()
        return Response(200, {})

    monkeypatch.setattr(client, "_send", send)
    monkeypatch.setattr(mcp_worker, "_verify_catalog", lambda _root: None)
    monkeypatch.setattr(mcp_worker, "smoke", lambda: None)
    return client, routes, calls


def test_deploy_uploads_the_modules_and_routes_only_the_mcp_hostname(cloudflare) -> None:
    client, routes, calls = cloudflare
    mcp_worker.deploy(client, ROOT)
    assert calls[:2] == [("GET", ZONE, None), ("GET", ROUTES, None)]
    method, path, payload = calls[2]
    assert (method, path) == ("PUT", SCRIPT)
    assert isinstance(payload, Multipart)
    message = BytesParser(policy=policy.default).parsebytes(
        f"Content-Type: {payload.content_type}\r\n\r\n".encode() + payload.data
    )
    parts = {
        part.get_param("name", header="Content-Disposition"): part for part in message.iter_parts()
    }
    assert set(parts) == {
        "metadata",
        "index.mjs",
        "worker/catalog.mjs",
        "worker/mcp.mjs",
        "client-js/src/mcp-fixtures.mjs",
    }
    assert b'"main_module": "index.mjs"' in parts["metadata"].get_payload(decode=True)
    assert b'"observability": {"enabled": false}' in parts["metadata"].get_payload(decode=True)
    assert calls[3] == (
        "POST",
        f"{SCRIPT}/subdomain",
        {"enabled": False, "previews_enabled": False},
    )
    assert routes[-1] == {
        "pattern": "mcp.loremfile.dev/*",
        "script": "loremfile-mcp",
        "id": "pilot",
    }


def test_first_deploy_detaches_the_pilot_route_if_smoke_fails(cloudflare, monkeypatch) -> None:
    client, routes, calls = cloudflare

    def fail() -> None:
        raise CloudflareError("smoke failed")

    monkeypatch.setattr(mcp_worker, "smoke", fail)
    with pytest.raises(CloudflareError, match="smoke failed"):
        mcp_worker.deploy(client, ROOT)
    assert calls[-1] == ("DELETE", f"{ROUTES}/pilot", None)
    assert [row["id"] for row in routes] == ["other"]


@pytest.mark.parametrize("operation", ["deploy", "unroute"])
def test_a_route_owned_by_a_different_worker_is_never_replaced(cloudflare, operation) -> None:
    client, routes, calls = cloudflare
    routes.append({"pattern": "mcp.loremfile.dev/*", "script": "someone-else", "id": "other-mcp"})
    with pytest.raises(CloudflareError, match="already claimed"):
        if operation == "deploy":
            mcp_worker.deploy(client, ROOT)
        else:
            mcp_worker.unroute(client)
    assert calls == [("GET", ZONE, None), ("GET", ROUTES, None)]


def test_rollback_is_for_the_pilot_script_only(cloudflare) -> None:
    client, _, calls = cloudflare
    version = UUID("12345678-1234-1234-1234-123456789abc")
    mcp_worker.rollback(client, version)
    assert calls == [
        ("GET", ZONE, None),
        (
            "POST",
            f"{SCRIPT}/deployments",
            {
                "strategy": "percentage",
                "versions": [{"version_id": str(version), "percentage": 100}],
            },
        ),
    ]


@pytest.mark.parametrize("body", [b'{"id": 1, "result": {}}', b"[]"])
def test_probe_names_itself_and_reports_malformed_rpc(monkeypatch, body) -> None:
    class Reply(BytesIO):
        def geturl(self):
            return mcp_worker.URL

    def open_reply(request, **_):
        assert request.get_header("User-agent") == VERIFY_USER_AGENT
        assert request.get_method() == "POST"
        reply = Reply(body)
        reply.headers = EmailMessage()
        reply.headers["Content-Type"] = "application/json"
        reply.headers["Cache-Control"] = "no-store"
        return reply

    monkeypatch.setattr(urllib.request, "urlopen", open_reply)
    if body == b"[]":
        with pytest.raises(CloudflareError, match="did not return a result"):
            mcp_worker._rpc("tools/list", {})
    else:
        assert mcp_worker._rpc("tools/list", {}) == {}


@pytest.mark.parametrize("errors", [0, 3])
def test_monitor_never_prints_analytics(monkeypatch, capsys, errors) -> None:
    data = {
        "sum": {"requests": 3210, "errors": errors},
        "quantiles": {"cpuTimeP50": 456, "cpuTimeP99": 789},
    }
    result = {"data": {"viewer": {"accounts": [{"workersInvocationsAdaptive": [data]}]}}}
    monkeypatch.setenv("CLOUDFLARE_ANALYTICS_TOKEN", "fake")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "account")
    monkeypatch.setattr(mcp_worker, "smoke", lambda: None)

    def post(_token, payload):
        assert payload["variables"]["script"] == "loremfile-mcp"
        return result

    monkeypatch.setattr(usage, "_post", post)
    if errors:
        with pytest.raises(CloudflareError, match=r"^MCP pilot invocation errors observed$"):
            mcp_worker.monitor()
    else:
        mcp_worker.monitor()
    assert capsys.readouterr() == ("", "")
