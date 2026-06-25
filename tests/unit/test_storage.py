"""Unit tests for webapp/storage.py using moto S3 mock."""

from __future__ import annotations

import os
import tempfile

import boto3
import pytest
from moto import mock_aws

_BUCKET = "test-bucket"
_REGION = "us-east-1"


@pytest.fixture()
def s3_storage():
    """Yield a Storage instance backed by a moto-mocked S3 bucket."""
    with mock_aws():
        boto3.client(
            "s3",
            region_name=_REGION,
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
        ).create_bucket(Bucket=_BUCKET)

        from webapp.storage import Storage

        yield Storage(
            endpoint_url=None,
            bucket=_BUCKET,
            access_key="testing",
            secret_key="testing",
            region=_REGION,
        )


# ── put_file / get_file ──────────────────────────────────────────────────────

def test_put_file_and_get_file_roundtrip(s3_storage, tmp_path):
    src = tmp_path / "upload.txt"
    src.write_text("hello from file")

    s3_storage.put_file("files/upload.txt", str(src))

    dst = tmp_path / "download.txt"
    s3_storage.get_file("files/upload.txt", str(dst))

    assert dst.read_text() == "hello from file"


# ── put_bytes / get_bytes ────────────────────────────────────────────────────

def test_put_bytes_and_get_bytes_roundtrip(s3_storage):
    payload = b"\x00\x01\x02binary data\xff"
    s3_storage.put_bytes("raw/data.bin", payload, content_type="application/octet-stream")
    assert s3_storage.get_bytes("raw/data.bin") == payload


def test_put_bytes_with_custom_content_type(s3_storage):
    s3_storage.put_bytes("doc/page.html", b"<html/>", content_type="text/html")
    assert s3_storage.get_bytes("doc/page.html") == b"<html/>"


# ── exists ───────────────────────────────────────────────────────────────────

def test_exists_returns_false_before_put(s3_storage):
    assert s3_storage.exists("nonexistent/key.txt") is False


def test_exists_returns_true_after_put(s3_storage):
    s3_storage.put_bytes("check/flag.txt", b"1")
    assert s3_storage.exists("check/flag.txt") is True


# ── list ─────────────────────────────────────────────────────────────────────

def test_list_returns_expected_keys_with_prefix(s3_storage):
    s3_storage.put_bytes("jobs/001/valve_list.csv", b"v")
    s3_storage.put_bytes("jobs/001/tiles/tile_0.png", b"t")
    s3_storage.put_bytes("jobs/002/valve_list.csv", b"v")
    s3_storage.put_bytes("uploads/user1/doc.pdf", b"p")

    keys = s3_storage.list("jobs/001/")
    assert sorted(keys) == ["jobs/001/tiles/tile_0.png", "jobs/001/valve_list.csv"]


def test_list_returns_empty_for_nonexistent_prefix(s3_storage):
    assert s3_storage.list("nothing/here/") == []


# ── presigned_url ─────────────────────────────────────────────────────────────

def test_presigned_url_returns_nonempty_http_string(s3_storage):
    s3_storage.put_bytes("assets/tile.png", b"png-data")
    url = s3_storage.presigned_url("assets/tile.png", expires=600)
    assert isinstance(url, str)
    assert url.startswith("http")
    assert len(url) > 10


# ── delete ───────────────────────────────────────────────────────────────────

def test_delete_removes_object(s3_storage):
    s3_storage.put_bytes("temp/file.txt", b"bye")
    assert s3_storage.exists("temp/file.txt") is True
    s3_storage.delete("temp/file.txt")
    assert s3_storage.exists("temp/file.txt") is False
