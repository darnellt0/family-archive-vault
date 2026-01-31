import logging
from pathlib import Path
from typing import List, Dict, Any

import boto3
from botocore.config import Config

from .config import (
    R2_ACCOUNT_ID,
    R2_ACCESS_KEY_ID,
    R2_SECRET_ACCESS_KEY,
    R2_BUCKET_NAME,
)

logger = logging.getLogger(__name__)


def get_r2_client():
    """Get a boto3 S3 client configured for Cloudflare R2."""
    if not R2_ACCOUNT_ID or not R2_ACCESS_KEY_ID or not R2_SECRET_ACCESS_KEY:
        raise RuntimeError("R2 credentials not configured. Set R2_ACCOUNT_ID, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY")

    return boto3.client(
        "s3",
        endpoint_url=f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com",
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"}
        ),
    )


def list_objects(client, bucket: str, prefix: str = "") -> List[Dict[str, Any]]:
    """List all objects in bucket, handling pagination."""
    paginator = client.get_paginator("list_objects_v2")
    objects = []

    paginate_kwargs = {"Bucket": bucket}
    if prefix:
        paginate_kwargs["Prefix"] = prefix

    for page in paginator.paginate(**paginate_kwargs):
        for obj in page.get("Contents", []):
            objects.append({
                "key": obj["Key"],
                "size": obj["Size"],
                "last_modified": obj["LastModified"],
                "etag": obj.get("ETag", "").strip('"'),
            })

    return objects


def download_object(client, bucket: str, key: str, dest_path: Path) -> bool:
    """Download an object from R2 to local path."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    logger.info(f"Downloading {key} to {dest_path}")
    client.download_file(bucket, key, str(dest_path))
    return True


def delete_object(client, bucket: str, key: str):
    """Delete an object from R2."""
    logger.info(f"Deleting {key} from R2")
    client.delete_object(Bucket=bucket, Key=key)


def get_object_metadata(client, bucket: str, key: str) -> Dict[str, Any]:
    """Get metadata for an object without downloading it."""
    response = client.head_object(Bucket=bucket, Key=key)
    return {
        "content_type": response.get("ContentType", "application/octet-stream"),
        "size": response.get("ContentLength", 0),
        "etag": response.get("ETag", "").strip('"'),
        "last_modified": response.get("LastModified"),
    }
