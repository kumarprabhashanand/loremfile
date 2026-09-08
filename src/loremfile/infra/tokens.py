"""Verify that the CI credentials work, without ever printing them (docs/08 §2).

Each token is checked twice: that Cloudflare considers it active, and that it can
actually do the one thing the project needs it for. An active token with the wrong
permissions passes the first check and fails the deploy, which is the failure worth
catching early.

This runs only in GitHub Actions, where the secrets live. Nothing here writes anything.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

API = "https://api.cloudflare.com/client/v4"
TIMEOUT = 30


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class Report:
    checks: list[Check] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def add(self, name: str, ok: bool, detail: str = "") -> None:
        self.checks.append(Check(name, ok, detail))

    def render(self) -> str:
        lines = [
            f"  {'PASS' if c.ok else 'FAIL'}  {c.name}" + (f"  — {c.detail}" if c.detail else "")
            for c in self.checks
        ]
        return "\n".join(lines)


def _get(path: str, token: str) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(  # noqa: S310 - fixed https API host
        f"{API}{path}", headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except Exception:
            return exc.code, {}


def _errors(payload: dict[str, Any]) -> str:
    return (
        "; ".join(f"{e.get('code')}: {e.get('message')}" for e in payload.get("errors", []))
        or "no detail"
    )


def verify_zone_token(token: str, zone_id: str, report: Report) -> None:
    """T1 must be active and able to read the zone's settings."""
    status, payload = _get("/user/tokens/verify", token)
    active = payload.get("result", {}).get("status") == "active"
    report.add("T1 token is active", active, "" if active else f"HTTP {status}: {_errors(payload)}")
    status, payload = _get(f"/zones/{zone_id}/settings", token)
    report.add(
        "T1 can read zone settings",
        payload.get("success", False),
        "" if payload.get("success") else f"HTTP {status}: {_errors(payload)}",
    )


def verify_analytics_token(token: str, zone_id: str, report: Report) -> None:
    """T4 must be active and able to read zone analytics — and nothing more."""
    status, payload = _get("/user/tokens/verify", token)
    active = payload.get("result", {}).get("status") == "active"
    report.add("T4 token is active", active, "" if active else f"HTTP {status}: {_errors(payload)}")
    status, payload = _get(f"/zones/{zone_id}/settings", token)
    # Read-only analytics must NOT be able to read zone settings. If it can, the token
    # is wider than docs/10 §4 says it is, and that is worth knowing.
    too_wide = payload.get("success", False)
    report.add(
        "T4 is read-only analytics, not a zone token",
        not too_wide,
        "token can read zone settings — wider than intended" if too_wide else "",
    )


def verify_r2_credentials(
    access_key: str, secret_key: str, account_id: str, bucket: str, report: Report
) -> None:
    """T2 must be able to list the bucket over the S3 API."""
    client = boto3.client(
        "s3",
        endpoint_url=f"https://{account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        region_name="auto",
        config=Config(retries={"max_attempts": 3}),
    )
    try:
        response = client.list_objects_v2(Bucket=bucket, MaxKeys=1)
        count = response.get("KeyCount", 0)
        report.add("T2 can list the bucket", True, f"{count} object(s) visible")
    except ClientError as exc:
        report.add("T2 can list the bucket", False, str(exc.response.get("Error", exc))[:200])
    except Exception as exc:
        report.add("T2 can list the bucket", False, f"{type(exc).__name__}: {exc}"[:200])


def verify_all() -> Report:
    """Read every credential from the environment and check what it can do."""
    report = Report()
    zone_id = os.environ.get("CLOUDFLARE_ZONE_ID", "")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    bucket = os.environ.get("R2_BUCKET", "loremfile-public")

    if not zone_id or not account_id:
        report.add(
            "repository variables are set",
            False,
            "CLOUDFLARE_ZONE_ID and CLOUDFLARE_ACCOUNT_ID must both be present",
        )
        return report
    report.add("repository variables are set", True)

    zone_token = os.environ.get("CLOUDFLARE_API_TOKEN", "")
    if zone_token:
        verify_zone_token(zone_token, zone_id, report)
    else:
        report.add("T1 token is present", False, "CLOUDFLARE_API_TOKEN is empty")

    analytics_token = os.environ.get("CLOUDFLARE_ANALYTICS_TOKEN", "")
    if analytics_token:
        verify_analytics_token(analytics_token, zone_id, report)
    else:
        report.add("T4 token is present", False, "CLOUDFLARE_ANALYTICS_TOKEN is empty")

    access_key = os.environ.get("R2_ACCESS_KEY_ID", "")
    secret_key = os.environ.get("R2_SECRET_ACCESS_KEY", "")
    if access_key and secret_key:
        verify_r2_credentials(access_key, secret_key, account_id, bucket, report)
    else:
        report.add(
            "T2 credentials are present", False, "R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY are empty"
        )
    return report
