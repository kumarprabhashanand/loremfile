"""The bucket side of the deploy (docs/09 §5).

`upload.py` decides *what* to do and is a pure function of (manifest, what is live, what
bytes are available). This module is the part that talks to R2, kept separate so the plan
stays testable without a bucket and so every write goes through one place.

**Why a HEAD per key rather than a listing.** `list_objects_v2` returns keys, sizes and
ETags but not user metadata, and an ETag is an MD5 (or a multipart digest), not the
`sha256` the manifest records. Comparing a published object with the manifest therefore
needs a HEAD. The listing still comes first so that only keys that actually exist are
HEADed: on a first deploy that is zero requests, and thereafter one per published fixture.

**Nothing here overwrites a fixture.** `put_fixture` is only ever called for a key the
plan marked `UPLOAD`, which by construction is a key the listing did not contain. The
bucket lock rules are the enforcement; this is the layer that does not even try.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from loremfile.config import (
    ASSET_CACHE_CONTROL,
    BUCKET,
    CATALOG_VERSION,
    FIXTURE_CACHE_CONTROL,
    SITE_CACHE_CONTROL,
)
from loremfile.infra.upload import (
    MULTIPART_CHUNK,
    MULTIPART_THREADS,
    MULTIPART_THRESHOLD,
    UNVERIFIABLE,
)


class R2Error(RuntimeError):
    """The bucket could not be reached, or answered with an error."""


def bucket_name() -> str:
    return os.environ.get("R2_BUCKET") or BUCKET


def _credential(*names: str) -> str:
    """The first of `names` set in the environment.

    `deploy.yml` exports R2's keys under the `AWS_*` names boto3 reads by default, while
    `infra.yml` and the probe use the `R2_*` names. Both are accepted rather than making
    one workflow's convention the tool's contract.
    """
    for name in names:
        value = os.environ.get(name)
        if value:
            return value
    raise R2Error(
        f"none of {', '.join(names)} is set; R2 credentials come from the GitHub "
        "`production` environment (AGENTS.md rule 4)."
    )


def client() -> Any:  # noqa: ANN401 - boto3 exposes no client type to annotate
    """An S3 client for T2, the bucket-scoped token."""
    import boto3  # noqa: PLC0415 - boto3 is only needed when a bucket is involved

    account = _credential("CLOUDFLARE_ACCOUNT_ID")
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=_credential("R2_ACCESS_KEY_ID", "AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=_credential("R2_SECRET_ACCESS_KEY", "AWS_SECRET_ACCESS_KEY"),
        region_name="auto",
    )


def list_keys(s3: Any, bucket: str, prefix: str = "") -> set[str]:  # noqa: ANN401
    """Every key in the bucket, paginated. One Class B operation per 1,000 keys."""
    keys: set[str] = set()
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {"Bucket": bucket, "MaxKeys": 1000}
        if prefix:
            kwargs["Prefix"] = prefix
        if token:
            kwargs["ContinuationToken"] = token
        response = s3.list_objects_v2(**kwargs)
        keys.update(str(item["Key"]) for item in response.get("Contents", []))
        if not response.get("IsTruncated"):
            return keys
        token = response.get("NextContinuationToken")
        if not token:  # pragma: no cover - defensive; R2 always supplies one
            return keys


def head_sha256(s3: Any, bucket: str, key: str) -> str:  # noqa: ANN401
    """The `sha256` metadata of a published object, or `UNVERIFIABLE`."""
    response = s3.head_object(Bucket=bucket, Key=key)
    metadata = {str(k).lower(): str(v) for k, v in (response.get("Metadata") or {}).items()}
    return metadata.get("sha256") or UNVERIFIABLE


def live_hashes(s3: Any, bucket: str, keys: list[str]) -> dict[str, str]:  # noqa: ANN401
    """Key -> published `sha256`, for the subset of `keys` the bucket holds."""
    present = list_keys(s3, bucket)
    return {key: head_sha256(s3, bucket, key) for key in keys if key in present}


def _transfer_config() -> Any:  # noqa: ANN401 - boto3 exposes no type for this either
    from boto3.s3.transfer import TransferConfig  # noqa: PLC0415

    return TransferConfig(
        multipart_threshold=MULTIPART_THRESHOLD,
        multipart_chunksize=MULTIPART_CHUNK,
        max_concurrency=MULTIPART_THREADS,
    )


def put_fixture(s3: Any, bucket: str, key: str, source: Path, *, mime: str, sha256: str) -> None:  # noqa: ANN401
    """Publish one fixture. Called only for a key the listing did not contain."""
    s3.upload_file(
        Filename=str(source),
        Bucket=bucket,
        Key=key,
        ExtraArgs={
            "ContentType": mime,
            "CacheControl": FIXTURE_CACHE_CONTROL,
            "ContentDisposition": f'inline; filename="{key.rsplit("/", 1)[-1]}"',
            "Metadata": {"sha256": sha256, "catalog-version": CATALOG_VERSION},
        },
        Config=_transfer_config(),
    )


def put_site(s3: Any, bucket: str, key: str, source: Path, *, mime: str, sha256: str) -> None:  # noqa: ANN401
    """Publish one site object. Site keys are mutable; fixtures are not.

    **No caller until M4.1.** `loremfile site build` does not exist yet, so nothing in
    this repository has ever run this function against a bucket. Its unit coverage proves
    the arguments it passes, not that a site object was ever written — the same caveat
    `release.py` carries, and for the same reason.
    """
    cache = ASSET_CACHE_CONTROL if key.startswith("assets/") else SITE_CACHE_CONTROL
    s3.upload_file(
        Filename=str(source),
        Bucket=bucket,
        Key=key,
        ExtraArgs={
            "ContentType": mime,
            "CacheControl": cache,
            "Metadata": {"sha256": sha256, "catalog-version": CATALOG_VERSION},
        },
        Config=_transfer_config(),
    )


def delete(s3: Any, bucket: str, key: str) -> None:  # noqa: ANN401
    """Remove one object. Reached only from a manifest tombstone (docs/09 §5)."""
    s3.delete_object(Bucket=bucket, Key=key)
