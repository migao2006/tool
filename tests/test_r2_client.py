from __future__ import annotations

from io import BytesIO
import sys
from types import SimpleNamespace
from typing import Any

import pytest

from src.data.object_storage.r2_client import (
    R2Client,
    R2ConfigurationError,
    R2Settings,
)


class FakeS3Error(Exception):
    def __init__(self, code: str, status: int) -> None:
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status},
        }
        super().__init__(code)


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], dict[str, Any]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("put_object", kwargs))
        identity = (kwargs["Bucket"], kwargs["Key"])
        if identity in self.objects and kwargs.get("IfNoneMatch") == "*":
            raise FakeS3Error("PreconditionFailed", 412)
        self.objects[identity] = {
            "body": kwargs["Body"],
            "content_type": kwargs.get("ContentType"),
            "metadata": kwargs.get("Metadata", {}),
        }
        return {"ETag": '"fake-etag"'}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("head_object", kwargs))
        identity = (kwargs["Bucket"], kwargs["Key"])
        if identity not in self.objects:
            raise FakeS3Error("NoSuchKey", 404)
        stored = self.objects[identity]
        return {
            "ContentLength": len(stored["body"]),
            "ContentType": stored["content_type"],
            "Metadata": stored["metadata"],
            "ETag": '"fake-etag"',
        }

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("get_object", kwargs))
        stored = self.objects[(kwargs["Bucket"], kwargs["Key"])]
        return {"Body": BytesIO(stored["body"])}

    def delete_object(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("delete_object", kwargs))
        self.objects.pop((kwargs["Bucket"], kwargs["Key"]), None)
        return {}


def settings() -> R2Settings:
    return R2Settings(
        account_id="account123",
        access_key_id="access-super-secret",
        secret_access_key="secret-super-secret",
        bucket_name="alpha-lens-archive",
    )


def test_client_loads_required_environment_and_builds_https_endpoint() -> None:
    fake = FakeS3Client()
    client = R2Client.from_env(
        {
            "R2_ACCOUNT_ID": "account123",
            "R2_ACCESS_KEY_ID": "access-key",
            "R2_SECRET_ACCESS_KEY": "secret-key",
            "R2_BUCKET_NAME": "archive",
        },
        s3_client=fake,
    )

    assert client.settings.endpoint_url == (
        "https://account123.r2.cloudflarestorage.com"
    )
    assert client.bucket_name == "archive"


def test_settings_repr_never_contains_credentials() -> None:
    rendered = repr(settings())

    assert "access-super-secret" not in rendered
    assert "secret-super-secret" not in rendered
    assert "alpha-lens-archive" in rendered


def test_default_s3_client_uses_cloudflare_endpoint_and_auto_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    fake_s3 = FakeS3Client()

    def client(service_name: str, **kwargs: object) -> FakeS3Client:
        calls.append((service_name, kwargs))
        return fake_s3

    monkeypatch.setitem(sys.modules, "boto3", SimpleNamespace(client=client))

    configured = settings()
    R2Client(configured)

    assert calls == [
        (
            "s3",
            {
                "endpoint_url": "https://account123.r2.cloudflarestorage.com",
                "aws_access_key_id": "access-super-secret",
                "aws_secret_access_key": "secret-super-secret",
                "region_name": "auto",
            },
        )
    ]


def test_client_reports_missing_variable_names_without_values() -> None:
    with pytest.raises(R2ConfigurationError, match="R2_SECRET_ACCESS_KEY"):
        _ = R2Client.from_env(
            {
                "R2_ACCOUNT_ID": "account123",
                "R2_ACCESS_KEY_ID": "access-key",
                "R2_BUCKET_NAME": "archive",
            },
            s3_client=FakeS3Client(),
        )


def test_put_if_absent_head_get_and_delete_round_trip() -> None:
    fake = FakeS3Client()
    client = R2Client(settings(), s3_client=fake)

    assert client.put_if_absent(
        "daily/2330.parquet",
        b"parquet-bytes",
        content_type="application/vnd.apache.parquet",
        metadata={"source": "finmind"},
    )
    assert not client.put_if_absent("daily/2330.parquet", b"replacement")

    metadata = client.head("daily/2330.parquet")
    assert metadata is not None
    assert metadata.content_length == len(b"parquet-bytes")
    assert metadata.content_type == "application/vnd.apache.parquet"
    assert metadata.metadata == {"source": "finmind"}
    assert client.get("daily/2330.parquet") == b"parquet-bytes"

    client.delete("daily/2330.parquet")
    assert client.head("daily/2330.parquet") is None


def test_non_precondition_storage_errors_are_not_hidden() -> None:
    class FailingS3Client(FakeS3Client):
        def put_object(self, **kwargs: Any) -> dict[str, Any]:
            raise FakeS3Error("AccessDenied", 403)

    client = R2Client(settings(), s3_client=FailingS3Client())

    with pytest.raises(FakeS3Error, match="AccessDenied"):
        client.put_if_absent("daily/2330.parquet", b"data")


@pytest.mark.parametrize(
    "key",
    ["", "   ", "/absolute-key", "../secret", "daily/../secret", "daily\\file"],
)
def test_object_operations_reject_invalid_keys(key: str) -> None:
    client = R2Client(settings(), s3_client=FakeS3Client())

    with pytest.raises(ValueError):
        client.head(key)
