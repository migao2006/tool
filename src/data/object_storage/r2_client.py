"""Small, secret-safe Cloudflare R2 adapter using the S3-compatible API."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
import re
from typing import Protocol, cast, runtime_checkable


_REQUIRED_ENVIRONMENT_VARIABLES = (
    "R2_ACCOUNT_ID",
    "R2_ACCESS_KEY_ID",
    "R2_SECRET_ACCESS_KEY",
    "R2_BUCKET_NAME",
)
_BUCKET_NAME = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


class R2ConfigurationError(ValueError):
    """Raised when the R2 environment contract is incomplete or unsafe."""


class S3CompatibleClient(Protocol):
    """Subset of the boto3 S3 client used by this adapter."""

    def put_object(self, **kwargs: object) -> Mapping[str, object]: ...

    def head_object(self, **kwargs: object) -> Mapping[str, object]: ...

    def get_object(self, **kwargs: object) -> Mapping[str, object]: ...

    def delete_object(self, **kwargs: object) -> Mapping[str, object]: ...


@runtime_checkable
class ReadableBody(Protocol):
    def read(self) -> bytes: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class R2Settings:
    """Validated R2 settings with credentials excluded from representations."""

    account_id: str
    access_key_id: str = field(repr=False)
    secret_access_key: str = field(repr=False)
    bucket_name: str

    def __post_init__(self) -> None:
        values = {
            "R2_ACCOUNT_ID": self.account_id,
            "R2_ACCESS_KEY_ID": self.access_key_id,
            "R2_SECRET_ACCESS_KEY": self.secret_access_key,
            "R2_BUCKET_NAME": self.bucket_name,
        }
        missing = [name for name, value in values.items() if not value.strip()]
        if missing:
            raise R2ConfigurationError(
                f"Missing required R2 settings: {', '.join(missing)}"
            )
        if not all(
            character.isalnum() or character == "-" for character in self.account_id
        ):
            raise R2ConfigurationError("R2_ACCOUNT_ID contains invalid characters")
        if _BUCKET_NAME.fullmatch(self.bucket_name) is None:
            raise R2ConfigurationError("R2_BUCKET_NAME is not a valid bucket name")

    @classmethod
    def from_env(cls, environment: Mapping[str, str] | None = None) -> "R2Settings":
        values = os.environ if environment is None else environment
        normalized = {
            name: values.get(name, "").strip()
            for name in _REQUIRED_ENVIRONMENT_VARIABLES
        }
        missing = [name for name, value in normalized.items() if not value]
        if missing:
            raise R2ConfigurationError(
                f"Missing required R2 environment variables: {', '.join(missing)}"
            )
        return cls(
            account_id=normalized["R2_ACCOUNT_ID"],
            access_key_id=normalized["R2_ACCESS_KEY_ID"],
            secret_access_key=normalized["R2_SECRET_ACCESS_KEY"],
            bucket_name=normalized["R2_BUCKET_NAME"],
        )

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"


@dataclass(frozen=True)
class ObjectMetadata:
    """Storage metadata returned without downloading an object's contents."""

    key: str
    content_length: int
    etag: str | None
    content_type: str | None
    metadata: Mapping[str, str]


class R2Client:
    """Bucket-scoped R2 operations suitable for archive and smoke-test flows."""

    def __init__(
        self,
        settings: R2Settings,
        *,
        s3_client: S3CompatibleClient | None = None,
    ) -> None:
        self.settings: R2Settings = settings
        self._s3: S3CompatibleClient = s3_client or _build_boto3_client(settings)

    @classmethod
    def from_env(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        s3_client: S3CompatibleClient | None = None,
    ) -> "R2Client":
        return cls(R2Settings.from_env(environment), s3_client=s3_client)

    @property
    def bucket_name(self) -> str:
        return self.settings.bucket_name

    def put_if_absent(
        self,
        key: str,
        body: bytes,
        *,
        content_type: str = "application/octet-stream",
        metadata: Mapping[str, str] | None = None,
    ) -> bool:
        """Write an object only when the key does not already exist.

        Returns ``True`` when written and ``False`` when R2 reports that the
        precondition failed because the key already exists.
        """

        object_key = _validate_key(key)
        request: dict[str, object] = {
            "Bucket": self.settings.bucket_name,
            "Key": object_key,
            "Body": body,
            "ContentType": content_type,
            "IfNoneMatch": "*",
        }
        if metadata:
            request["Metadata"] = dict(metadata)
        try:
            _ = self._s3.put_object(**request)
        except Exception as error:
            if _has_error_status(
                error, {409, 412}, {"ConditionalRequestConflict", "PreconditionFailed"}
            ):
                return False
            raise
        return True

    def head(self, key: str) -> ObjectMetadata | None:
        """Return object metadata, or ``None`` when the key does not exist."""

        object_key = _validate_key(key)
        try:
            response = self._s3.head_object(
                Bucket=self.settings.bucket_name,
                Key=object_key,
            )
        except Exception as error:
            if _has_error_status(error, {404}, {"404", "NoSuchKey", "NotFound"}):
                return None
            raise
        raw_metadata: object = response.get("Metadata", {})
        if isinstance(raw_metadata, Mapping):
            typed_metadata = cast(Mapping[object, object], raw_metadata)
            metadata = {str(name): str(value) for name, value in typed_metadata.items()}
        else:
            metadata = {}
        return ObjectMetadata(
            key=object_key,
            content_length=_content_length(response.get("ContentLength")),
            etag=_optional_string(response.get("ETag")),
            content_type=_optional_string(response.get("ContentType")),
            metadata=metadata,
        )

    def get(self, key: str) -> bytes:
        """Download an object's entire byte payload."""

        response = self._s3.get_object(
            Bucket=self.settings.bucket_name,
            Key=_validate_key(key),
        )
        body = response.get("Body")
        if not isinstance(body, ReadableBody):
            raise RuntimeError("R2 get_object response did not contain a readable body")
        try:
            payload = body.read()
        finally:
            body.close()
        return payload

    def delete(self, key: str) -> None:
        """Delete an object. S3 delete semantics are idempotent."""

        _ = self._s3.delete_object(
            Bucket=self.settings.bucket_name,
            Key=_validate_key(key),
        )


def _build_boto3_client(settings: R2Settings) -> S3CompatibleClient:
    import boto3  # pyright: ignore[reportMissingTypeStubs]

    return cast(
        S3CompatibleClient,
        boto3.client(  # pyright: ignore[reportUnknownMemberType]
            "s3",
            endpoint_url=settings.endpoint_url,
            aws_access_key_id=settings.access_key_id,
            aws_secret_access_key=settings.secret_access_key,
            region_name="auto",
        ),
    )


def _validate_key(key: str) -> str:
    if not key or not key.strip():
        raise ValueError("R2 object key must not be empty")
    if "\\" in key or any(part in {"", ".", ".."} for part in key.split("/")):
        raise ValueError("R2 object key must be a safe relative path")
    if any(ord(character) < 32 for character in key):
        raise ValueError("R2 object key must not contain control characters")
    return key


def _optional_string(value: object) -> str | None:
    return str(value) if value is not None else None


def _content_length(value: object) -> int:
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise TypeError("R2 ContentLength must be an integer")
    return int(value)


def _has_error_status(
    error: Exception,
    expected_statuses: set[int],
    expected_codes: set[str],
) -> bool:
    response: object = getattr(error, "response", None)
    if not isinstance(response, Mapping):
        return False
    typed_response = cast(Mapping[object, object], response)
    error_details: object = typed_response.get("Error", {})
    response_metadata: object = typed_response.get("ResponseMetadata", {})
    code: object = None
    if isinstance(error_details, Mapping):
        code = cast(Mapping[object, object], error_details).get("Code")
    status: object = None
    if isinstance(response_metadata, Mapping):
        status = cast(Mapping[object, object], response_metadata).get("HTTPStatusCode")
    return str(code) in expected_codes or (
        isinstance(status, int) and status in expected_statuses
    )
