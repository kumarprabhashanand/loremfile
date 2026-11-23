"""Record the deployment smoke's actual requests for the Worker parity test."""

from __future__ import annotations

import json
import sys
from typing import Any
from unittest.mock import patch

from loremfile.infra import mcp_worker

requests: list[tuple[str, dict[str, Any]]] = []


def record(method: str, params: dict[str, Any]) -> dict[str, Any]:
    requests.append((method, params))
    # Responses let smoke proceed. The Node test replays the requests against both servers.
    if method == "tools/list":
        return {"tools": [{"name": "list_fixtures"}, {"name": "describe_fixture"}]}
    if params["name"] == "describe_fixture":
        return {"structuredContent": {"path": params["arguments"]["path"]}}
    return {"structuredContent": {"fixtures": [{}]}}


if __name__ == "__main__":
    with patch.object(mcp_worker, "_rpc", side_effect=record):
        mcp_worker.smoke()
    json.dump(requests, sys.stdout)
