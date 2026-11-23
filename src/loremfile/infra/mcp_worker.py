"""Build, deploy, roll back or monitor the MCP pilot from the existing CI workflows."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from loremfile import config
from loremfile.infra import usage, verify_live
from loremfile.infra.cloudflare_api import (
    Client,
    CloudflareError,
    Multipart,
    Response,
    ZoneScopeError,
)
from loremfile.manifest import Manifest
from loremfile.site import build, mcp, routes

SCRIPT = "loremfile-mcp"
HOST = f"mcp.{config.SITE_HOST}"
ROUTE = f"{HOST}/*"
URL = f"https://{HOST}/mcp"
MODULES = ("worker/mcp.mjs", "worker/catalog.mjs", "client-js/src/mcp-fixtures.mjs")

METRICS_QUERY = """
query Pilot($account: string!, $start: Time!, $end: Time!, $script: string!) {
  viewer {
    accounts(filter: {accountTag: $account}) {
      workersInvocationsAdaptive(
        limit: 1
        filter: {scriptName: $script, datetime_geq: $start, datetime_leq: $end}
      ) {
        sum { requests errors }
        quantiles { cpuTimeP50 cpuTimeP99 }
      }
    }
  }
}
"""


def modules(root: Path) -> dict[str, bytes]:
    tools = json.loads((root / "client-js/src/tools.json").read_bytes())
    version = json.loads((root / "client-js/package.json").read_bytes())["version"]
    formats = json.loads((root / "formats.json").read_bytes())["formats"]
    arguments = (
        tools,
        {"name": "loremfile", "version": version},
        [row["format"] for row in formats],
    )
    encoded = ", ".join(json.dumps(arg, ensure_ascii=True) for arg in arguments)
    entry = (
        'import { createHandler } from "./worker/mcp.mjs";\n'
        f"export default {{ fetch: createHandler({encoded}) }};\n"
    )
    return {"index.mjs": entry.encode(), **{name: (root / name).read_bytes() for name in MODULES}}


def upload_body(files: dict[str, bytes]) -> Multipart:
    metadata = {
        "main_module": "index.mjs",
        "compatibility_date": "2026-11-23",
        "observability": {"enabled": False},
        "logpush": False,
    }
    boundary = uuid4().hex
    parts = [
        f'--{boundary}\r\nContent-Disposition: form-data; name="metadata"\r\n'
        f"Content-Type: application/json\r\n\r\n{json.dumps(metadata)}\r\n".encode()
    ]
    for name, content in files.items():
        header = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{name}"\r\n'
            "Content-Type: application/javascript+module\r\n\r\n"
        )
        parts.append(header.encode() + content + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return Multipart(b"".join(parts), f"multipart/form-data; boundary={boundary}")


def _require(response: Response, operation: str) -> Any:  # noqa: ANN401 - API results vary
    if not response.ok:
        raise CloudflareError(f"{operation}: {response.why()}")
    return response.result


def _route_path(client: Client) -> str:
    return f"/zones/{client.zone_id}/workers/routes"


def _script_path(client: Client) -> str:
    return f"/accounts/{client.account_id}/workers/scripts/{SCRIPT}"


def find_route(client: Client) -> str | None:
    current = _require(client.get(_route_path(client)), "list Worker routes")
    found = [row for row in current if row["pattern"] == ROUTE]
    if not found:
        return None
    if len(found) != 1 or found[0].get("script") != SCRIPT:
        raise CloudflareError(f"{ROUTE} is already claimed by a different configuration")
    return str(found[0]["id"])


def _verify_catalog(root: Path) -> None:
    manifest = Manifest.load(root / "manifest.json")
    for key, expected in (
        (routes.MCP_INDEX_KEY, mcp.compact_index(manifest)),
        (routes.format_index_key("pdf"), build.format_index(manifest, "pdf")),
    ):
        response = verify_live.fetch(routes.public_path(key), method="GET")
        digest = hashlib.sha256(expected).hexdigest()
        findings = verify_live.check_site_key(key, digest, response)
        if any(finding.status is not verify_live.Status.OK for finding in findings):
            raise CloudflareError(
                f"{routes.public_path(key)} failed its live check; run site deploy"
            )


def deploy(client: Client, root: Path) -> None:
    client.verify_zone()
    route_id = find_route(client)
    _verify_catalog(root)
    script = _script_path(client)
    _require(client.request("PUT", script, upload_body(modules(root))), "upload MCP Worker")
    _require(
        client.post(f"{script}/subdomain", {"enabled": False, "previews_enabled": False}),
        "disable workers.dev and preview URLs",
    )
    if route_id is None:
        _require(
            client.post(_route_path(client), {"pattern": ROUTE, "script": SCRIPT}), "route MCP"
        )
    try:
        smoke()
    except CloudflareError:
        if route_id is None:
            unroute(client)
        raise


def rollback(client: Client, version: UUID) -> None:
    client.verify_zone()
    script = _script_path(client)
    _require(
        client.post(
            f"{script}/deployments",
            {
                "strategy": "percentage",
                "versions": [{"version_id": str(version), "percentage": 100}],
            },
        ),
        "roll back the MCP Worker",
    )


def unroute(client: Client) -> None:
    client.verify_zone()
    route_id = find_route(client)
    if route_id is not None:
        _require(client.delete(f"{_route_path(client)}/{route_id}"), "unroute the MCP Worker")


def _rpc(method: str, params: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        URL,
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode(),
        headers=config.with_agent(
            {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
                "MCP-Protocol-Version": "2025-11-25",
            },
            config.VERIFY_USER_AGENT,
        ),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # noqa: S310
            if (
                response.geturl() != URL
                or response.headers.get_content_type() != "application/json"
                or response.headers.get("Cache-Control") != "no-store"
                or "Set-Cookie" in response.headers
                or "Mcp-Session-Id" in response.headers
            ):
                raise CloudflareError(f"MCP {method} broke the HTTP contract")
            message = json.load(response)
    except (OSError, ValueError) as exc:
        raise CloudflareError(f"MCP {method} did not answer over HTTPS: {exc}") from exc
    result = message.get("result") if isinstance(message, dict) else None
    if not isinstance(result, dict) or message.get("id") != 1 or result.get("isError"):
        raise CloudflareError(f"MCP {method} did not return a result")
    return result


def smoke() -> None:
    tools = _rpc("tools/list", {}).get("tools", [])
    if not isinstance(tools, list) or [
        tool.get("name") if isinstance(tool, dict) else None for tool in tools
    ] != ["list_fixtures", "describe_fixture"]:
        raise CloudflareError("MCP tools/list did not return the two pilot tools")
    path = "pdf/sample.pdf"
    result = _rpc("tools/call", {"name": "describe_fixture", "arguments": {"path": path}})
    fixture = result.get("structuredContent")
    if not isinstance(fixture, dict) or fixture.get("path") != path:
        raise CloudflareError("MCP describe_fixture did not describe the PDF alias")
    result = _rpc("tools/call", {"name": "list_fixtures", "arguments": {"limit": 1}})
    listing = result.get("structuredContent")
    if not isinstance(listing, dict) or not listing.get("fixtures"):
        raise CloudflareError("MCP list_fixtures did not read the cross-format index")


def monitor() -> None:
    """The public job reports health only. Aggregates stay in Cloudflare and process memory."""
    smoke()
    end = dt.datetime.now(dt.UTC)
    start = end - dt.timedelta(days=1)
    try:
        document = usage._post(
            usage._token(),
            {
                "query": METRICS_QUERY,
                "variables": {
                    "account": usage._account(),
                    "start": usage._stamp(start),
                    "end": usage._stamp(end),
                    "script": SCRIPT,
                },
            },
        )
        rows = document["data"]["viewer"]["accounts"][0]["workersInvocationsAdaptive"]
        (row,) = rows
        requests, errors = (row["sum"][key] for key in ("requests", "errors"))
        p50, p99 = (row["quantiles"][key] for key in ("cpuTimeP50", "cpuTimeP99"))
        if requests <= 0 or min(errors, p50, p99) < 0 or p99 < p50:
            raise ValueError("unusable analytics")
    except (KeyError, IndexError, TypeError, ValueError, OSError, usage.UsageError):
        raise CloudflareError("MCP pilot metrics unavailable") from None
    if errors:
        raise CloudflareError("MCP pilot invocation errors observed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("build", "deploy", "rollback", "unroute", "monitor"))
    parser.add_argument("--version", type=UUID)
    args = parser.parse_args()
    root = config.repo_root()
    try:
        if args.mode == "build":
            for key, content in modules(root).items():
                target = root / "build/mcp-worker" / key
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
        elif args.mode == "monitor":
            monitor()
        else:
            client = Client.from_env()
            if args.mode == "deploy":
                deploy(client, root)
            elif args.mode == "rollback":
                if args.version is None:
                    parser.error("rollback requires --version")
                rollback(client, args.version)
                smoke()
            else:
                unroute(client)
    except (CloudflareError, ZoneScopeError, ValueError, OSError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
