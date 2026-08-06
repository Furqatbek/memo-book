"""S3-compatible object storage. Sync boto3, called from async code via
anyio.to_thread. The bucket is private; access happens only through
presigned URLs (15 min for uploads — spec Part 11)."""
import boto3
from botocore.config import Config as BotoConfig

from app.config import get_settings

UPLOAD_URL_EXPIRY_S = 15 * 60
DISPLAY_URL_EXPIRY_S = 60 * 60

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
        config=BotoConfig(retries={"max_attempts": 2}),
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


def presign_put(key: str, content_type: str) -> str:
    return _presigner().generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket(), "Key": key, "ContentType": content_type},
        ExpiresIn=UPLOAD_URL_EXPIRY_S,
    )


def presign_get(key: str, expires_in: int = DISPLAY_URL_EXPIRY_S) -> str:
    return _presigner().generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket(), "Key": key},
        ExpiresIn=expires_in,
    )


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
