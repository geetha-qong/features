"""Shared pytest fixtures for the qong_poc test suite."""

from __future__ import annotations

import os
import sys

import boto3
import pytest
from moto import mock_aws

# Make the project root importable without installation
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_BUCKET = "test-bucket"
_REGION = "us-east-1"


@pytest.fixture()
def storage(monkeypatch):
    """Storage instance wired to a moto-mocked S3 bucket."""
    # Must set env vars before importing storage so the singleton picks them up
    monkeypatch.setenv("STORAGE_ENDPOINT_URL", "")
    monkeypatch.setenv("STORAGE_BUCKET", _BUCKET)
    monkeypatch.setenv("STORAGE_ACCESS_KEY", "testing")
    monkeypatch.setenv("STORAGE_SECRET_KEY", "testing")
    monkeypatch.setenv("STORAGE_REGION", _REGION)

    # Reset singleton so each test gets a fresh client
    import webapp.storage as storage_mod
    monkeypatch.setattr(storage_mod, "_singleton", None)

    with mock_aws():
        # Create the bucket inside the mock context
        boto3.client(
            "s3",
            region_name=_REGION,
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        ).create_bucket(Bucket=_BUCKET)

        from webapp.storage import Storage
        s = Storage(
            endpoint_url=None,
            bucket=_BUCKET,
            access_key="testing",
            secret_key="testing",
            region=_REGION,
        )
        yield s
