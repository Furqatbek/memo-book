"""S3-compatible object storage. Sync boto3, called from async code via
anyio.to_thread. The bucket is private; access happens only through
presigned URLs (15 min for uploads — spec Part 11)."""
import boto3
from botocore.config import Config as BotoConfig

from app.config import get_settings

UPLOAD_URL_EXPIRY_S = 15 * 60
DISPLAY_URL_EXPIRY_S = 60 * 60

_client = None


def client():
    global _client
    if _client is None:
        s = get_settings()
        _client = boto3.client(
            "s3",
            endpoint_url=s.s3_endpoint_url,
            aws_access_key_id=s.s3_access_key,
            aws_secret_access_key=s.s3_secret_key,
            region_name=s.s3_region,
            config=BotoConfig(retries={"max_attempts": 2}),
        )
    return _client


def set_client(c) -> None:
    """Test seam: inject a mocked client."""
    global _client
    _client = c


def bucket() -> str:
    return get_settings().s3_bucket


def presign_put(key: str, content_type: str) -> str:
    return client().generate_presigned_url(
        "put_object",
        Params={"Bucket": bucket(), "Key": key, "ContentType": content_type},
        ExpiresIn=UPLOAD_URL_EXPIRY_S,
    )


def presign_get(key: str, expires_in: int = DISPLAY_URL_EXPIRY_S) -> str:
    return client().generate_presigned_url(
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
