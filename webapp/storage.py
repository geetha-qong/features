"""S3-compatible object storage adapter (boto3).

Works against AWS S3, GCS via S3 interop, and MinIO — only the endpoint URL
and credentials change between environments.

Env vars (read by get_storage()):
    STORAGE_ENDPOINT_URL   optional; blank for AWS S3, set for GCS / MinIO
    STORAGE_BUCKET         required
    STORAGE_ACCESS_KEY     required
    STORAGE_SECRET_KEY     required
    STORAGE_REGION         default "us-east-1"
"""

from __future__ import annotations

import os
from typing import Optional

import boto3
from botocore.client import Config

__all__ = ["Storage", "get_storage"]

_singleton: Optional["Storage"] = None


class Storage:
    def __init__(
        self,
        endpoint_url: Optional[str],
        bucket: str,
        access_key: str,
        secret_key: str,
        region: str = "us-east-1",
    ) -> None:
        self.bucket = bucket
        # path-style addressing required for MinIO and GCS interop
        self._client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    # ── file-level helpers ─────────────────────────────────────────────────────

    def put_file(self, key: str, local_path: str) -> None:
        self._client.upload_file(local_path, self.bucket, key)

    def get_file(self, key: str, local_path: str) -> None:
        self._client.download_file(self.bucket, key, local_path)

    # ── bytes-level helpers ────────────────────────────────────────────────────

    def put_bytes(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )

    def get_bytes(self, key: str) -> bytes:
        response = self._client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    # ── URL / metadata ─────────────────────────────────────────────────────────

    def presigned_url(self, key: str, expires: int = 3600) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires,
        )

    def list(self, prefix: str) -> list:
        """Return all object keys under *prefix*."""
        paginator = self._client.get_paginator("list_objects_v2")
        keys = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                keys.append(obj["Key"])
        return keys

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self._client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)


def get_storage() -> Storage:
    """Return process-wide singleton configured from environment variables."""
    global _singleton
    if _singleton is None:
        _singleton = Storage(
            endpoint_url=os.environ.get("STORAGE_ENDPOINT_URL") or None,
            bucket=os.environ["STORAGE_BUCKET"],
            access_key=os.environ["STORAGE_ACCESS_KEY"],
            secret_key=os.environ["STORAGE_SECRET_KEY"],
            region=os.environ.get("STORAGE_REGION", "us-east-1"),
        )
    return _singleton
