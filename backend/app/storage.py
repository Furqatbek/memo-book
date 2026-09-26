"""S3-compatible object storage. Sync boto3, called from async code via
anyio.to_thread. The bucket is private; access happens only through
presigned URLs (15 min for uploads — spec Part 11)."""
import boto3
from botocore.config import Config as BotoConfig

from app.config import get_settings

# A PUT URL is a write credential and is used the moment it is issued, so it
# stays short (spec Part 11).
UPLOAD_URL_EXPIRY_S = 15 * 60

# A GET URL for a photo or a design's artwork has to outlive the SITTING it
# was issued in, not the request. The editor asks for these once, when the
# book loads, and never asks again — so at one hour a customer who spent
# ninety minutes arranging their book watched every thumbnail and every
# canvas image turn into a broken icon, with nothing on screen to explain it
# and nothing to do but reload. A day covers any real session; someone who
# comes back tomorrow reloads the page and gets fresh URLs anyway.
#
# The cost is that a leaked URL stays good for longer. These sign the
# customer's own photos and our own cover artwork — not the print files,
# which are handled separately and deliberately.
DISPLAY_URL_EXPIRY_S = 24 * 60 * 60

# SigV4's hard ceiling on a presigned URL: seven days, and S3 rejects the
# request outright rather than shortening it. Anything that has to outlive a
# week must therefore be reached through a route of OURS that signs a fresh
# URL on each visit — which is how the flip-video link works, and why its
# thirty days live in the token rather than in the signature.
#
# `presign_get` clamps to this so an invalid URL cannot be minted at all.
# A test asserts no caller asks for more, so the clamp should never fire;
# it is there because a silently-truncated link is easier to debug than a
# 400 from the storage service at delivery time.
MAX_PRESIGN_EXPIRY_S = 7 * 24 * 60 * 60

_client = None
_presign_client = None


def _make_client(endpoint: str):
    s = get_settings()
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=s.s3_access_key,
        aws_secret_access_key=s.s3_secret_key,
        region_name=s.s3_region,
        # SigV4 explicitly. Left to boto's default, `generate_presigned_post`
        # produced a SigV2 policy (`AWSAccessKeyId` + `signature`), which is
        # the deprecated form: AWS has removed it in newer regions and it is
        # not what any current S3-compatible service is tested against. The
        # upload cap rides on that policy, so the one credential that must
        # not be silently ignored is the one that was being signed the old
        # way.
        config=BotoConfig(retries={"max_attempts": 2},
                          signature_version="s3v4"),
    )


def client():
    """Server-side operations: the INTERNAL endpoint (e.g. http://minio:9000
    inside compose) — ingest/render traffic never leaves the network."""
    global _client
    if _client is None:
        _client = _make_client(get_settings().s3_endpoint_url)
    return _client


def _presigner():
    """URL signing: the PUBLIC endpoint browsers can reach. Falls back to the
    internal endpoint when no public one is configured (plain local dev)."""
    global _presign_client
    if _presign_client is None:
        s = get_settings()
        _presign_client = _make_client(s.s3_public_url or s.s3_endpoint_url)
    return _presign_client


def set_client(c) -> None:
    """Test seam: inject a mocked client (used for ops and presigning both)."""
    global _client, _presign_client
    _client = c
    _presign_client = c


def bucket() -> str:
    return get_settings().s3_bucket


def presign_post(key: str, content_type: str, max_bytes: int,
                 min_bytes: int = 1) -> dict:
    """A one-shot upload credential that CANNOT exceed `max_bytes`.

    This replaces a presigned PUT, and the reason is the whole point of the
    thing: a presigned PUT signs the bucket, the key and the content type,
    and says nothing about length. The size a client declares when it asks
    for the URL is therefore decorative — it can promise one megabyte and
    send five gigabytes, and the first thing that notices is the worker
    that reads the object.

    A POST policy is a signed DOCUMENT of conditions. `content-length-range`
    is one of them, so the storage service refuses an oversized body before
    it lands rather than after. The cap moves from something we check
    afterwards to something the upload cannot break.

    Returns `{"url": ..., "fields": {...}}`. The browser must send every
    field, unmodified, as multipart form data with the file LAST — that
    ordering is part of the S3 POST contract, not a suggestion.

    NOTE ON WHERE THIS IS ENFORCED: by the storage service, not by us.
    `moto`, which the tests and the dev server use, does NOT enforce
    `content-length-range` — an oversized body is accepted there. So the
    tests assert that the signed policy CONTAINS the condition, which is
    the part we are responsible for, and `head_size` below remains a real
    second line of defence rather than a formality.
    """
    return _presigner().generate_presigned_post(
        bucket(), key,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type},
            ["content-length-range", min_bytes, max_bytes],
        ],
        ExpiresIn=UPLOAD_URL_EXPIRY_S,
    )


def presign_get(key: str, expires_in: int = DISPLAY_URL_EXPIRY_S) -> str:
    return _presigner().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket(), "Key": key},
        ExpiresIn=min(expires_in, MAX_PRESIGN_EXPIRY_S),
    )


def head_size(key: str) -> int | None:
    """How many bytes are actually in storage, or None if nothing is.

    A presigned PUT signs the bucket, key and content type — NOT the
    length. The size a client declared when it asked for the URL is
    therefore decorative: it can declare 1 MB and upload 5 GB. This is how
    the size is found out before anything reads the object into memory.
    """
    try:
        return int(client().head_object(Bucket=bucket(), Key=key)["ContentLength"])
    except Exception:  # noqa: BLE001 — a missing object is an ordinary answer
        return None


def delete_key(key: str) -> None:
    try:
        client().delete_object(Bucket=bucket(), Key=key)
    except Exception:  # noqa: BLE001 — best effort; the reaper catches the rest
        pass


def get_bytes(key: str) -> bytes:
    return client().get_object(Bucket=bucket(), Key=key)["Body"].read()


def put_bytes(key: str, data: bytes, content_type: str) -> None:
    client().put_object(Bucket=bucket(), Key=key, Body=data, ContentType=content_type)


def delete_keys(keys: list[str]) -> None:
    existing = [k for k in keys if k]
    if existing:
        client().delete_objects(
            Bucket=bucket(), Delete={"Objects": [{"Key": k} for k in existing]}
        )


def object_exists(key: str) -> bool:
    try:
        client().head_object(Bucket=bucket(), Key=key)
        return True
    except Exception:  # noqa: BLE001 — missing object, any provider's 404 shape
        return False
