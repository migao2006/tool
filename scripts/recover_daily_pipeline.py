"""Report and boundedly rerun trusted failures in the daily production pipelines."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from http.client import HTTPResponse
import io
import json
import os
from pathlib import Path
import re
import socket
import sys
import time
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zipfile import BadZipFile, ZipFile


API_VERSION = "2026-03-10"
IMPORT_ARTIFACT_FILENAME = "import-market-data-result.json"
MAX_API_RESPONSE_BYTES = 1_048_576
MAX_ARTIFACT_ARCHIVE_BYTES = 65_536
MAX_ARTIFACT_RESULT_BYTES = 4_096
ISSUE_MARKER_PREFIX = "daily-pipeline-recovery:run-id="
_REPOSITORY = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+")
_SHA = re.compile(r"[0-9a-f]{40}")
_SAFE_REASON_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
_KNOWN_CONCLUSIONS = frozenset(
    {
        "action_required",
        "cancelled",
        "failure",
        "neutral",
        "skipped",
        "stale",
        "startup_failure",
        "success",
        "timed_out",
    }
)
_FAILED_JOB_CONCLUSIONS = frozenset(
    {"action_required", "cancelled", "failure", "stale", "startup_failure", "timed_out"}
)
_IMPORT_RESULT_KEYS = frozenset(
    {
        "schema_version",
        "status",
        "reason_code",
        "requested_as_of_date",
        "twse_source_date",
        "tpex_source_date",
        "as_of_date",
    }
)
_FEATURE_FAILURE_RESULT_KEYS = frozenset(
    {
        "build_status",
        "generated_at",
        "label_status",
        "reason_codes",
        "system_status",
        "usage_scope",
    }
)
_PRODUCTION_FAILURE_RESULT_KEYS = frozenset(
    {
        "as_of_date",
        "generated_at",
        "market",
        "message",
        "reason_codes",
        "status",
    }
)
_TRANSIENT_DAILY_REASON_CODES = frozenset({"SUPABASE_CONNECTION_ERROR"})


class RecoveryError(RuntimeError):
    """A fail-closed recovery-controller error with a safe constant code."""


class GitHubApiError(RecoveryError):
    """A GitHub API call failed without exposing response or request details."""


class ArtifactValidationError(RecoveryError):
    """An attempt-qualified result artifact was absent or invalid."""


class _StripCrossOriginAuthorization(HTTPRedirectHandler):
    """Follow artifact redirects without forwarding the GitHub bearer token."""

    def redirect_request(  # type: ignore[override]
        self,
        request: Request,
        file_pointer: Any,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> Request | None:
        redirected = super().redirect_request(
            request,
            file_pointer,
            code,
            message,
            headers,
            new_url,
        )
        if redirected is None:
            return None
        original = urlparse(request.full_url)
        target = urlparse(new_url)
        if (original.scheme, original.hostname, original.port) != (
            target.scheme,
            target.hostname,
            target.port,
        ):
            redirected.remove_header("Authorization")
            redirected.remove_header("X-GitHub-Api-Version")
        return redirected


def urlopen(request: Request, *, timeout: float) -> HTTPResponse:
    """Open one URL with authorization-stripping cross-origin redirects."""

    opener = build_opener(_StripCrossOriginAuthorization())
    return cast(HTTPResponse, opener.open(request, timeout=timeout))


class GitHubClient(Protocol):
    def request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        expected_statuses: tuple[int, ...] = (200,),
    ) -> Any: ...

    def request_bytes(
        self,
        method: str,
        path: str,
        *,
        expected_statuses: tuple[int, ...] = (200,),
        maximum_bytes: int,
    ) -> bytes: ...


class GitHubApiClient:
    """Small no-retry GitHub REST client built only on the Python standard library."""

    def __init__(
        self,
        *,
        token: str,
        api_url: str = "https://api.github.com",
        timeout_seconds: float = 30,
    ) -> None:
        parsed = urlparse(api_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise GitHubApiError("INVALID_GITHUB_API_URL")
        if not token:
            raise GitHubApiError("MISSING_GITHUB_TOKEN")
        if timeout_seconds <= 0 or timeout_seconds > 120:
            raise GitHubApiError("INVALID_GITHUB_API_TIMEOUT")
        self._token = token
        self._api_url = api_url.rstrip("/")
        self._timeout_seconds = timeout_seconds

    def request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        expected_statuses: tuple[int, ...] = (200,),
    ) -> Any:
        raw = self._request(
            method,
            path,
            body=body,
            expected_statuses=expected_statuses,
            maximum_bytes=MAX_API_RESPONSE_BYTES,
        )
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GitHubApiError("INVALID_GITHUB_JSON_RESPONSE") from error

    def request_bytes(
        self,
        method: str,
        path: str,
        *,
        expected_statuses: tuple[int, ...] = (200,),
        maximum_bytes: int,
    ) -> bytes:
        return self._request(
            method,
            path,
            body=None,
            expected_statuses=expected_statuses,
            maximum_bytes=maximum_bytes,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None,
        expected_statuses: tuple[int, ...],
        maximum_bytes: int,
    ) -> bytes:
        if method not in {"GET", "PATCH", "POST"}:
            raise GitHubApiError("UNSUPPORTED_HTTP_METHOD")
        if not path.startswith("/") or "://" in path or "\r" in path or "\n" in path:
            raise GitHubApiError("INVALID_GITHUB_API_PATH")
        if not expected_statuses or maximum_bytes <= 0:
            raise GitHubApiError("INVALID_GITHUB_API_REQUEST")
        encoded_body = None
        if body is not None:
            encoded_body = json.dumps(
                body,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        request = Request(
            f"{self._api_url}{path}",
            data=encoded_body,
            method=method,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "alpha-lens-daily-pipeline-recovery",
                "X-GitHub-Api-Version": API_VERSION,
            },
        )
        # Intentionally one attempt for every request. In particular, mutating
        # calls are never blindly replayed after an ambiguous transport timeout.
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                status = int(response.status)
                if status not in expected_statuses:
                    raise GitHubApiError("UNEXPECTED_HTTP_STATUS")
                raw = response.read(maximum_bytes + 1)
        except HTTPError as error:
            raise GitHubApiError("UNEXPECTED_HTTP_STATUS") from error
        except (URLError, TimeoutError, socket.timeout, OSError) as error:
            raise GitHubApiError("GITHUB_API_TRANSPORT_ERROR") from error
        if len(raw) > maximum_bytes:
            raise GitHubApiError("GITHUB_API_RESPONSE_TOO_LARGE")
        return raw


@dataclass(frozen=True)
class WorkflowPolicy:
    name: str
    path: str
    kind: str
    allowed_events: frozenset[str]
    maximum_attempt: int


@dataclass(frozen=True)
class TrustedRun:
    run_id: int
    attempt: int
    status: str
    conclusion: str
    workflow: WorkflowPolicy
    event: str
    head_branch: str
    head_sha: str


@dataclass(frozen=True)
class ImportResult:
    status: str
    reason_code: str
    requested_as_of_date: str | None
    twse_source_date: str | None
    tpex_source_date: str | None
    as_of_date: str | None


@dataclass(frozen=True)
class DailyFailureResult:
    reason_code: str


@dataclass(frozen=True)
class FailureScope:
    report_stage: str
    stages: tuple[str, ...]
    has_unknown: bool


@dataclass(frozen=True)
class IssueRecord:
    number: int
    state: str


@dataclass(frozen=True)
class Report:
    run: TrustedRun
    stage: str
    reason_code: str
    decision: str
    requested_as_of_date: str | None = None
    twse_source_date: str | None = None
    tpex_source_date: str | None = None


@dataclass(frozen=True)
class RecoveryResult:
    decision: str
    workflow: str
    run_id: int
    attempt: int
    issue_number: int | None
    rerun_requested: bool


_POLICIES = {
    ("Import market data", ".github/workflows/import-market-data.yml"): WorkflowPolicy(
        name="Import market data",
        path=".github/workflows/import-market-data.yml",
        kind="IMPORT",
        allowed_events=frozenset({"schedule", "workflow_dispatch"}),
        maximum_attempt=2,
    ),
    ("Daily research model", ".github/workflows/daily-research-model.yml"): WorkflowPolicy(
        name="Daily research model",
        path=".github/workflows/daily-research-model.yml",
        kind="DAILY",
        allowed_events=frozenset({"push", "schedule", "workflow_dispatch", "workflow_run"}),
        maximum_attempt=3,
    ),
}

_STAGE_NAMES = {
    "import": "IMPORT",
    "Import current market data": "IMPORT",
    "resolve": "RESOLVE",
    "publish-current-bars": "PUBLISH_CURRENT_BARS",
    "build-features (TWSE)": "BUILD_FEATURES_TWSE",
    "build-features (TPEX)": "BUILD_FEATURES_TPEX",
    "export-security-catalog (TWSE)": "EXPORT_SECURITY_CATALOG_TWSE",
    "export-security-catalog (TPEX)": "EXPORT_SECURITY_CATALOG_TPEX",
    "publish-staging (TWSE)": "PUBLISH_STAGING_TWSE",
    "publish-staging (TPEX)": "PUBLISH_STAGING_TPEX",
    "publish-production (TWSE)": "PUBLISH_PRODUCTION_TWSE",
    "publish-production (TPEX)": "PUBLISH_PRODUCTION_TPEX",
}
_STAGE_ORDER = {stage: index for index, stage in enumerate(_STAGE_NAMES.values())}
_DAILY_FAILURE_ARTIFACT_SPECS = {
    "BUILD_FEATURES_TWSE": (
        "daily-research-features-TWSE",
        "twse-research-features-audit.json",
        "FEATURE",
        "TWSE",
    ),
    "BUILD_FEATURES_TPEX": (
        "daily-research-features-TPEX",
        "tpex-research-features-audit.json",
        "FEATURE",
        "TPEX",
    ),
    "PUBLISH_PRODUCTION_TWSE": (
        "daily-research-production-TWSE",
        "twse-production-publish-report.json",
        "PRODUCTION",
        "TWSE",
    ),
    "PUBLISH_PRODUCTION_TPEX": (
        "daily-research-production-TPEX",
        "tpex-production-publish-report.json",
        "PRODUCTION",
        "TPEX",
    ),
}


def _mapping(value: object, code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise RecoveryError(code)
    return cast(Mapping[str, Any], value)


def _positive_integer(value: object, code: str) -> int:
    if type(value) is not int or value <= 0:
        raise RecoveryError(code)
    return value


def _exact_string(value: object, code: str) -> str:
    if not isinstance(value, str) or not value:
        raise RecoveryError(code)
    return value


def _repository_name(value: object, code: str) -> str:
    rendered = _exact_string(value, code)
    if not _REPOSITORY.fullmatch(rendered):
        raise RecoveryError(code)
    return rendered


def _nested_repository_name(value: object, code: str) -> str:
    payload = _mapping(value, code)
    return _repository_name(payload.get("full_name"), code)


def _trusted_event(event: Mapping[str, Any], repository: str) -> TrustedRun:
    if not _REPOSITORY.fullmatch(repository):
        raise RecoveryError("INVALID_CURRENT_REPOSITORY")
    if event.get("action") != "completed":
        raise RecoveryError("UNTRUSTED_EVENT_ACTION")
    if _nested_repository_name(event.get("repository"), "UNTRUSTED_EVENT_REPOSITORY") != repository:
        raise RecoveryError("UNTRUSTED_EVENT_REPOSITORY")
    workflow_run = _mapping(event.get("workflow_run"), "UNTRUSTED_WORKFLOW_RUN")
    run_repository = _nested_repository_name(
        workflow_run.get("repository"),
        "UNTRUSTED_RUN_REPOSITORY",
    )
    head_repository = _nested_repository_name(
        workflow_run.get("head_repository"),
        "UNTRUSTED_HEAD_REPOSITORY",
    )
    if run_repository != repository or head_repository != repository:
        raise RecoveryError("UNTRUSTED_RUN_REPOSITORY")
    name = _exact_string(workflow_run.get("name"), "UNTRUSTED_WORKFLOW_NAME")
    path = _exact_string(workflow_run.get("path"), "UNTRUSTED_WORKFLOW_PATH")
    policy = _POLICIES.get((name, path))
    if policy is None:
        raise RecoveryError("UNTRUSTED_WORKFLOW_IDENTITY")
    run_id = _positive_integer(workflow_run.get("id"), "UNTRUSTED_RUN_ID")
    attempt = _positive_integer(workflow_run.get("run_attempt"), "UNTRUSTED_RUN_ATTEMPT")
    status = _exact_string(workflow_run.get("status"), "UNTRUSTED_RUN_STATUS")
    conclusion = _exact_string(workflow_run.get("conclusion"), "UNTRUSTED_RUN_CONCLUSION")
    event_name = _exact_string(workflow_run.get("event"), "UNTRUSTED_RUN_EVENT")
    branch = _exact_string(workflow_run.get("head_branch"), "UNTRUSTED_HEAD_BRANCH")
    sha = _exact_string(workflow_run.get("head_sha"), "UNTRUSTED_HEAD_SHA")
    if status != "completed" or conclusion not in _KNOWN_CONCLUSIONS:
        raise RecoveryError("UNTRUSTED_RUN_COMPLETION")
    if event_name not in policy.allowed_events:
        raise RecoveryError("UNTRUSTED_RUN_EVENT")
    if branch != "main" or not _SHA.fullmatch(sha):
        raise RecoveryError("UNTRUSTED_RUN_HEAD")
    return TrustedRun(
        run_id=run_id,
        attempt=attempt,
        status=status,
        conclusion=conclusion,
        workflow=policy,
        event=event_name,
        head_branch=branch,
        head_sha=sha,
    )


def _server_run_matches(
    payload: object,
    *,
    expected: TrustedRun,
    repository: str,
) -> bool:
    if not isinstance(payload, Mapping):
        return False
    server = cast(Mapping[str, Any], payload)
    try:
        run_repository = _nested_repository_name(server.get("repository"), "INVALID_SERVER_RUN")
        head_repository = _nested_repository_name(
            server.get("head_repository"),
            "INVALID_SERVER_RUN",
        )
    except RecoveryError:
        return False
    return (
        type(server.get("id")) is int
        and server.get("id") == expected.run_id
        and type(server.get("run_attempt")) is int
        and server.get("run_attempt") == expected.attempt
        and server.get("status") == expected.status
        and server.get("conclusion") == expected.conclusion
        and server.get("name") == expected.workflow.name
        and server.get("path") == expected.workflow.path
        and server.get("event") == expected.event
        and server.get("head_branch") == expected.head_branch
        and server.get("head_sha") == expected.head_sha
        and run_repository == repository
        and head_repository == repository
    )


def _get_server_run(client: GitHubClient, repository: str, run_id: int) -> object:
    return client.request_json(
        "GET",
        f"/repos/{repository}/actions/runs/{run_id}",
    )


def _get_initial_main_sha(client: GitHubClient, repository: str) -> str:
    metadata = _mapping(
        client.request_json("GET", f"/repos/{repository}"),
        "INVALID_REPOSITORY_RESPONSE",
    )
    if metadata.get("full_name") != repository or metadata.get("default_branch") != "main":
        raise RecoveryError("DEFAULT_BRANCH_IS_NOT_TRUSTED_MAIN")
    return _get_main_sha(client, repository)


def _get_main_sha(client: GitHubClient, repository: str) -> str:
    branch = _mapping(
        client.request_json("GET", f"/repos/{repository}/branches/main"),
        "INVALID_MAIN_BRANCH_RESPONSE",
    )
    commit = _mapping(branch.get("commit"), "INVALID_MAIN_BRANCH_RESPONSE")
    sha = commit.get("sha")
    if branch.get("name") != "main" or not isinstance(sha, str) or not _SHA.fullmatch(sha):
        raise RecoveryError("INVALID_MAIN_BRANCH_RESPONSE")
    return sha


def _failed_scope(
    client: GitHubClient,
    repository: str,
    run: TrustedRun,
) -> FailureScope:
    stages: list[str] = []
    saw_unknown_failure = False
    for page in range(1, 101):
        payload = _mapping(
            client.request_json(
                "GET",
                (
                    f"/repos/{repository}/actions/runs/{run.run_id}/attempts/"
                    f"{run.attempt}/jobs?filter=all&per_page=100&page={page}"
                ),
            ),
            "INVALID_JOBS_RESPONSE",
        )
        jobs = payload.get("jobs")
        if not isinstance(jobs, list):
            raise RecoveryError("INVALID_JOBS_RESPONSE")
        for raw_job in jobs:
            if not isinstance(raw_job, Mapping):
                saw_unknown_failure = True
                continue
            conclusion = raw_job.get("conclusion")
            if conclusion not in _FAILED_JOB_CONCLUSIONS:
                continue
            name = raw_job.get("name")
            if isinstance(name, str) and name in _STAGE_NAMES:
                stages.append(_STAGE_NAMES[name])
            else:
                saw_unknown_failure = True
        if len(jobs) < 100:
            break
    else:
        raise RecoveryError("JOBS_PAGINATION_LIMIT_EXCEEDED")
    ordered = tuple(sorted(set(stages), key=lambda stage: _STAGE_ORDER[stage]))
    has_unknown = saw_unknown_failure or not ordered
    report_stage = ordered[0] if ordered else "UNKNOWN"
    return FailureScope(
        report_stage=report_stage,
        stages=ordered,
        has_unknown=has_unknown,
    )


def _issue_marker(run_id: int) -> str:
    return f"<!-- {ISSUE_MARKER_PREFIX}{run_id} -->"


def _find_issue(
    client: GitHubClient,
    repository: str,
    run_id: int,
) -> IssueRecord | None:
    marker = _issue_marker(run_id)
    matches: list[IssueRecord] = []
    for page in range(1, 101):
        payload = client.request_json(
            "GET",
            (
                f"/repos/{repository}/issues?creator=github-actions%5Bbot%5D"
                f"&state=all&per_page=10&page={page}"
            ),
        )
        if not isinstance(payload, list):
            raise RecoveryError("INVALID_ISSUES_RESPONSE")
        for raw_issue in payload:
            if not isinstance(raw_issue, Mapping) or "pull_request" in raw_issue:
                continue
            body = raw_issue.get("body")
            number = raw_issue.get("number")
            state = raw_issue.get("state")
            user = raw_issue.get("user")
            performed_via_app = raw_issue.get("performed_via_github_app")
            trusted_user = (
                isinstance(user, Mapping)
                and user.get("login") == "github-actions[bot]"
                and user.get("type") == "Bot"
            )
            trusted_app = performed_via_app is None or (
                isinstance(performed_via_app, Mapping)
                and performed_via_app.get("slug") == "github-actions"
            )
            first_line = body.splitlines()[0] if isinstance(body, str) and body else ""
            if (
                first_line == marker
                and trusted_user
                and trusted_app
                and type(number) is int
                and number > 0
                and state in {"open", "closed"}
            ):
                matches.append(IssueRecord(number=number, state=state))
        if len(payload) < 10:
            break
    else:
        raise RecoveryError("ISSUES_PAGINATION_LIMIT_EXCEEDED")
    if not matches:
        return None
    if len(matches) != 1:
        raise RecoveryError("DUPLICATE_RECOVERY_ISSUES")
    return matches[0]


def _render_report(report: Report, *, include_marker: bool) -> str:
    run = report.run
    lines = []
    if include_marker:
        lines.append(_issue_marker(run.run_id))
    lines.extend(
        [
            "## Daily pipeline recovery",
            "",
            f"- Workflow: `{run.workflow.name}`",
            f"- Stage: `{report.stage}`",
            f"- Reason: `{report.reason_code}`",
            f"- Attempt: `{run.attempt}/{run.workflow.maximum_attempt}`",
            f"- Decision: `{report.decision}`",
            "- Recovery mode: `RECONCILE_LATEST_VALID`",
            (
                "- Run: "
                f"https://github.com/{{repository}}/actions/runs/{run.run_id}"
            ),
            f"- Commit: `{run.head_sha[:12]}`",
        ]
    )
    if report.requested_as_of_date is not None:
        lines.append(f"- Requested date: `{report.requested_as_of_date}`")
    if report.twse_source_date is not None:
        lines.append(f"- TWSE source date: `{report.twse_source_date}`")
    if report.tpex_source_date is not None:
        lines.append(f"- TPEx source date: `{report.tpex_source_date}`")
    return "\n".join(lines) + "\n"


def _report_body(report: Report, repository: str) -> str:
    return _render_report(report, include_marker=True).replace("{repository}", repository)


def _write_summary(path: Path | None, report: Report, repository: str) -> None:
    if path is None:
        return
    rendered = _render_report(report, include_marker=False).replace("{repository}", repository)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        _ = stream.write(rendered)


def _create_issue(
    client: GitHubClient,
    repository: str,
    report: Report,
) -> IssueRecord:
    payload = _mapping(
        client.request_json(
            "POST",
            f"/repos/{repository}/issues",
            body={
                "title": f"[Daily pipeline recovery] {report.run.workflow.name} run {report.run.run_id}",
                "body": _report_body(report, repository),
            },
            expected_statuses=(201,),
        ),
        "INVALID_CREATED_ISSUE_RESPONSE",
    )
    number = _positive_integer(payload.get("number"), "INVALID_CREATED_ISSUE_RESPONSE")
    return IssueRecord(number=number, state="open")


def _update_issue(
    client: GitHubClient,
    repository: str,
    issue: IssueRecord,
    report: Report,
    *,
    close: bool,
) -> IssueRecord:
    state = "closed" if close else "open"
    payload = _mapping(
        client.request_json(
            "PATCH",
            f"/repos/{repository}/issues/{issue.number}",
            body={
                "title": f"[Daily pipeline recovery] {report.run.workflow.name} run {report.run.run_id}",
                "body": _report_body(report, repository),
                "state": state,
            },
        ),
        "INVALID_UPDATED_ISSUE_RESPONSE",
    )
    number = _positive_integer(payload.get("number"), "INVALID_UPDATED_ISSUE_RESPONSE")
    if number != issue.number or payload.get("state") != state:
        raise RecoveryError("INVALID_UPDATED_ISSUE_RESPONSE")
    return IssueRecord(number=number, state=state)


def _persist_report(
    client: GitHubClient,
    repository: str,
    report: Report,
    *,
    issue: IssueRecord | None,
    close: bool,
) -> IssueRecord:
    current = issue or _create_issue(client, repository, report)
    if issue is None and not close:
        return current
    return _update_issue(
        client,
        repository,
        current,
        report,
        close=close,
    )


def _strict_iso_date(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ArtifactValidationError("INVALID_IMPORT_RESULT_DATE")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ArtifactValidationError("INVALID_IMPORT_RESULT_DATE") from error
    if parsed.isoformat() != value:
        raise ArtifactValidationError("INVALID_IMPORT_RESULT_DATE")
    return value


def _strict_timestamp(value: object) -> None:
    if not isinstance(value, str) or len(value) > 64:
        raise ArtifactValidationError("INVALID_RESULT_TIMESTAMP")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as error:
        raise ArtifactValidationError("INVALID_RESULT_TIMESTAMP") from error
    if parsed.tzinfo is None:
        raise ArtifactValidationError("INVALID_RESULT_TIMESTAMP")


def _single_reason_code(value: object) -> str:
    if (
        not isinstance(value, list)
        or len(value) != 1
        or not isinstance(value[0], str)
        or not _SAFE_REASON_CODE.fullmatch(value[0])
    ):
        raise ArtifactValidationError("INVALID_DAILY_RESULT_REASON")
    return value[0]


def _parse_import_result(raw: bytes) -> ImportResult:
    if len(raw) > MAX_ARTIFACT_RESULT_BYTES:
        raise ArtifactValidationError("IMPORT_RESULT_TOO_LARGE")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactValidationError("INVALID_IMPORT_RESULT_JSON") from error
    if not isinstance(payload, dict) or not set(payload).issubset(_IMPORT_RESULT_KEYS):
        raise ArtifactValidationError("INVALID_IMPORT_RESULT_SCHEMA")
    if type(payload.get("schema_version")) is not int or payload.get("schema_version") != 1:
        raise ArtifactValidationError("INVALID_IMPORT_RESULT_SCHEMA")
    status = payload.get("status")
    reason_code = payload.get("reason_code")
    if status not in {"PASS", "DEFERRED", "FAIL"}:
        raise ArtifactValidationError("INVALID_IMPORT_RESULT_STATUS")
    if not isinstance(reason_code, str) or not _SAFE_REASON_CODE.fullmatch(reason_code):
        raise ArtifactValidationError("INVALID_IMPORT_RESULT_REASON")
    requested = _strict_iso_date(payload.get("requested_as_of_date"))
    twse = _strict_iso_date(payload.get("twse_source_date"))
    tpex = _strict_iso_date(payload.get("tpex_source_date"))
    as_of_date = _strict_iso_date(payload.get("as_of_date"))
    if requested is None:
        raise ArtifactValidationError("INVALID_IMPORT_RESULT_REQUESTED_DATE")
    if status != "PASS" and as_of_date is not None:
        raise ArtifactValidationError("INVALID_IMPORT_RESULT_AS_OF_DATE")
    if (
        status == "PASS"
        and (
            reason_code != "IMPORT_COMPLETED"
            or as_of_date is None
            or twse is None
            or tpex is None
            or twse != as_of_date
            or tpex != as_of_date
        )
    ):
        raise ArtifactValidationError("INVALID_IMPORT_RESULT_SUCCESS")
    if (
        status == "DEFERRED"
        and (
            reason_code != "SOURCE_MARKET_DATE_MISMATCH"
            or twse is None
            or tpex is None
            or twse == tpex
        )
    ):
        raise ArtifactValidationError("INVALID_IMPORT_RESULT_MISMATCH")
    return ImportResult(
        status=status,
        reason_code=reason_code,
        requested_as_of_date=requested,
        twse_source_date=twse,
        tpex_source_date=tpex,
        as_of_date=as_of_date,
    )


def _load_attempt_artifact_file(
    client: GitHubClient,
    repository: str,
    run: TrustedRun,
    *,
    artifact_name: str,
    filename: str,
) -> bytes:
    matches: list[Mapping[str, Any]] = []
    for page in range(1, 101):
        payload = _mapping(
            client.request_json(
                "GET",
                (
                    f"/repos/{repository}/actions/runs/{run.run_id}/artifacts?"
                    f"per_page=100&page={page}"
                ),
            ),
            "INVALID_ARTIFACTS_RESPONSE",
        )
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            raise ArtifactValidationError("INVALID_ARTIFACTS_RESPONSE")
        for artifact in artifacts:
            if (
                isinstance(artifact, Mapping)
                and artifact.get("name") == artifact_name
                and artifact.get("expired") is False
            ):
                matches.append(cast(Mapping[str, Any], artifact))
        if len(artifacts) < 100:
            break
    else:
        raise ArtifactValidationError("ARTIFACTS_PAGINATION_LIMIT_EXCEEDED")
    if len(matches) != 1:
        raise ArtifactValidationError("ATTEMPT_ARTIFACT_NOT_UNIQUE")
    raw_artifact_id = matches[0].get("id")
    if type(raw_artifact_id) is not int or raw_artifact_id <= 0:
        raise ArtifactValidationError("INVALID_ARTIFACT_ID")
    artifact_id = raw_artifact_id
    archive = client.request_bytes(
        "GET",
        f"/repos/{repository}/actions/artifacts/{artifact_id}/zip",
        maximum_bytes=MAX_ARTIFACT_ARCHIVE_BYTES,
    )
    try:
        with ZipFile(io.BytesIO(archive)) as zipped:
            entries = zipped.infolist()
            if (
                len(entries) != 1
                or entries[0].filename != filename
                or entries[0].is_dir()
                or entries[0].file_size > MAX_ARTIFACT_RESULT_BYTES
            ):
                raise ArtifactValidationError("INVALID_ATTEMPT_RESULT_ARCHIVE")
            raw = zipped.read(entries[0])
    except (BadZipFile, RuntimeError) as error:
        raise ArtifactValidationError("INVALID_ATTEMPT_RESULT_ARCHIVE") from error
    return raw


def _load_import_result(
    client: GitHubClient,
    repository: str,
    run: TrustedRun,
) -> ImportResult:
    raw = _load_attempt_artifact_file(
        client,
        repository,
        run,
        artifact_name=f"import-market-data-result-{run.run_id}-{run.attempt}",
        filename=IMPORT_ARTIFACT_FILENAME,
    )
    return _parse_import_result(raw)


def _parse_daily_failure_result(
    raw: bytes,
    *,
    kind: str,
    market: str,
) -> DailyFailureResult:
    if len(raw) > MAX_ARTIFACT_RESULT_BYTES:
        raise ArtifactValidationError("DAILY_RESULT_TOO_LARGE")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ArtifactValidationError("INVALID_DAILY_RESULT_JSON") from error
    if not isinstance(payload, dict):
        raise ArtifactValidationError("INVALID_DAILY_RESULT_SCHEMA")
    reason_code = _single_reason_code(payload.get("reason_codes"))
    _strict_timestamp(payload.get("generated_at"))
    if kind == "FEATURE":
        if (
            set(payload) != _FEATURE_FAILURE_RESULT_KEYS
            or payload.get("build_status") != "FAIL"
            or payload.get("system_status") != "FAIL"
            or payload.get("label_status") != "LABELS_NOT_ASSEMBLED"
            or payload.get("usage_scope") != "FEATURE_RESEARCH_ONLY"
        ):
            raise ArtifactValidationError("INVALID_DAILY_FEATURE_RESULT")
    elif kind == "PRODUCTION":
        message = payload.get("message")
        if (
            set(payload) != _PRODUCTION_FAILURE_RESULT_KEYS
            or payload.get("status") != "FAIL"
            or payload.get("market") != market
            or _strict_iso_date(payload.get("as_of_date")) is None
            or not isinstance(message, str)
            or len(message) > 1_024
        ):
            raise ArtifactValidationError("INVALID_DAILY_PRODUCTION_RESULT")
    else:
        raise ArtifactValidationError("INVALID_DAILY_RESULT_KIND")
    return DailyFailureResult(reason_code=reason_code)


def _load_daily_failure_result(
    client: GitHubClient,
    repository: str,
    run: TrustedRun,
    *,
    stage: str,
) -> DailyFailureResult:
    specification = _DAILY_FAILURE_ARTIFACT_SPECS.get(stage)
    if specification is None:
        raise ArtifactValidationError("DAILY_STAGE_HAS_NO_TRANSIENT_RESULT")
    artifact_prefix, filename, kind, market = specification
    raw = _load_attempt_artifact_file(
        client,
        repository,
        run,
        artifact_name=f"{artifact_prefix}-{run.run_id}-{run.attempt}",
        filename=filename,
    )
    return _parse_daily_failure_result(raw, kind=kind, market=market)


def _result(
    run: TrustedRun,
    *,
    decision: str,
    issue: IssueRecord | None,
    rerun_requested: bool,
) -> RecoveryResult:
    return RecoveryResult(
        decision=decision,
        workflow=run.workflow.name,
        run_id=run.run_id,
        attempt=run.attempt,
        issue_number=issue.number if issue else None,
        rerun_requested=rerun_requested,
    )


def _finalize_without_retry(
    *,
    client: GitHubClient,
    repository: str,
    summary_path: Path | None,
    report: Report,
    issue: IssueRecord | None,
    close: bool,
) -> RecoveryResult:
    persisted = _persist_report(
        client,
        repository,
        report,
        issue=issue,
        close=close,
    )
    _write_summary(summary_path, report, repository)
    return _result(
        report.run,
        decision=report.decision,
        issue=persisted,
        rerun_requested=False,
    )


def process_workflow_run(
    event: Mapping[str, Any],
    *,
    client: GitHubClient,
    repository: str,
    sleep: Callable[[int], None] = time.sleep,
    summary_path: Path | None = None,
) -> RecoveryResult:
    """Validate one completed workflow_run event, report it, and maybe rerun it."""

    run = _trusted_event(event, repository)
    server_run = _get_server_run(client, repository, run.run_id)
    if not _server_run_matches(server_run, expected=run, repository=repository):
        report = Report(
            run=run,
            stage="WORKFLOW",
            reason_code="SERVER_STATE_CHANGED",
            decision="STATE_CHANGED",
        )
        _write_summary(summary_path, report, repository)
        return _result(run, decision="STATE_CHANGED", issue=None, rerun_requested=False)

    main_sha = _get_initial_main_sha(client, repository)
    failure_scope: FailureScope | None = None
    if run.conclusion == "success":
        stage = "WORKFLOW"
    else:
        failure_scope = _failed_scope(client, repository, run)
        stage = failure_scope.report_stage
    existing_issue = _find_issue(client, repository, run.run_id)

    if run.head_sha != main_sha:
        report = Report(
            run=run,
            stage=stage,
            reason_code="HEAD_SHA_SUPERSEDED",
            decision="SUPERSEDED",
        )
        return _finalize_without_retry(
            client=client,
            repository=repository,
            summary_path=summary_path,
            report=report,
            issue=existing_issue,
            close=True,
        )

    if run.conclusion == "success":
        report = Report(
            run=run,
            stage="WORKFLOW",
            reason_code="WORKFLOW_SUCCEEDED",
            decision="RECOVERED" if existing_issue else "SUCCESS",
        )
        if existing_issue is None:
            _write_summary(summary_path, report, repository)
            return _result(run, decision="SUCCESS", issue=None, rerun_requested=False)
        return _finalize_without_retry(
            client=client,
            repository=repository,
            summary_path=summary_path,
            report=report,
            issue=existing_issue,
            close=True,
        )

    requested_date: str | None = None
    twse_date: str | None = None
    tpex_date: str | None = None
    eligible = False
    reason_code: str
    terminal_decision: str | None = None
    delay_seconds: int | None = None

    if run.workflow.kind == "IMPORT":
        if run.conclusion != "failure":
            reason_code = f"CONCLUSION_{run.conclusion.upper()}"
            terminal_decision = "INELIGIBLE"
        else:
            try:
                import_result = _load_import_result(client, repository, run)
            except ArtifactValidationError:
                reason_code = "IMPORT_RESULT_UNVERIFIED"
                terminal_decision = "UNVERIFIED_IMPORT_RESULT"
            else:
                requested_date = import_result.requested_as_of_date
                twse_date = import_result.twse_source_date
                tpex_date = import_result.tpex_source_date
                eligible = (
                    import_result.status == "DEFERRED"
                    and import_result.reason_code == "SOURCE_MARKET_DATE_MISMATCH"
                    and twse_date is not None
                    and tpex_date is not None
                    and twse_date != tpex_date
                )
                if eligible:
                    reason_code = "SOURCE_MARKET_DATE_MISMATCH"
                    delay_seconds = 900
                else:
                    reason_code = import_result.reason_code
                    terminal_decision = "NON_RETRYABLE"
    else:
        if run.conclusion == "timed_out":
            eligible = True
            reason_code = "WORKFLOW_TIMED_OUT"
            delay_seconds = 300 if run.attempt == 1 else 900
        elif run.conclusion == "failure":
            if failure_scope is None:
                raise RecoveryError("MISSING_DAILY_FAILURE_SCOPE")
            if failure_scope.has_unknown:
                reason_code = "DAILY_RESULT_UNVERIFIED"
                terminal_decision = "UNVERIFIED_DAILY_RESULT"
            else:
                try:
                    daily_results = [
                        _load_daily_failure_result(
                            client,
                            repository,
                            run,
                            stage=failed_stage,
                        )
                        for failed_stage in failure_scope.stages
                    ]
                except ArtifactValidationError:
                    reason_code = "DAILY_RESULT_UNVERIFIED"
                    terminal_decision = "UNVERIFIED_DAILY_RESULT"
                else:
                    non_retryable = next(
                        (
                            result.reason_code
                            for result in daily_results
                            if result.reason_code not in _TRANSIENT_DAILY_REASON_CODES
                        ),
                        None,
                    )
                    if non_retryable is not None:
                        reason_code = non_retryable
                        terminal_decision = "NON_RETRYABLE"
                    else:
                        eligible = True
                        reason_code = "SUPABASE_CONNECTION_ERROR"
                        delay_seconds = 300 if run.attempt == 1 else 900
        else:
            reason_code = f"CONCLUSION_{run.conclusion.upper()}"
            terminal_decision = "INELIGIBLE"

    if eligible and run.attempt >= run.workflow.maximum_attempt:
        terminal_decision = "EXHAUSTED"
        delay_seconds = None

    if terminal_decision is not None:
        report = Report(
            run=run,
            stage=stage,
            reason_code=reason_code,
            decision=terminal_decision,
            requested_as_of_date=requested_date,
            twse_source_date=twse_date,
            tpex_source_date=tpex_date,
        )
        return _finalize_without_retry(
            client=client,
            repository=repository,
            summary_path=summary_path,
            report=report,
            issue=existing_issue,
            close=False,
        )

    if not eligible or delay_seconds is None:
        raise RecoveryError("INVALID_RECOVERY_POLICY_STATE")

    pending = Report(
        run=run,
        stage=stage,
        reason_code=reason_code,
        decision="RETRY_PENDING",
        requested_as_of_date=requested_date,
        twse_source_date=twse_date,
        tpex_source_date=tpex_date,
    )
    persisted = _persist_report(
        client,
        repository,
        pending,
        issue=existing_issue,
        close=False,
    )

    sleep(delay_seconds)

    refreshed_run = _get_server_run(client, repository, run.run_id)
    if not _server_run_matches(refreshed_run, expected=run, repository=repository):
        changed = Report(
            run=run,
            stage=stage,
            reason_code="SERVER_STATE_CHANGED",
            decision="STATE_CHANGED",
            requested_as_of_date=requested_date,
            twse_source_date=twse_date,
            tpex_source_date=tpex_date,
        )
        persisted = _persist_report(
            client,
            repository,
            changed,
            issue=persisted,
            close=False,
        )
        _write_summary(summary_path, changed, repository)
        return _result(run, decision="STATE_CHANGED", issue=persisted, rerun_requested=False)

    refreshed_main_sha = _get_main_sha(client, repository)
    if refreshed_main_sha != run.head_sha:
        superseded = Report(
            run=run,
            stage=stage,
            reason_code="HEAD_SHA_SUPERSEDED",
            decision="SUPERSEDED",
            requested_as_of_date=requested_date,
            twse_source_date=twse_date,
            tpex_source_date=tpex_date,
        )
        persisted = _persist_report(
            client,
            repository,
            superseded,
            issue=persisted,
            close=True,
        )
        _write_summary(summary_path, superseded, repository)
        return _result(run, decision="SUPERSEDED", issue=persisted, rerun_requested=False)

    try:
        _ = client.request_json(
            "POST",
            f"/repos/{repository}/actions/runs/{run.run_id}/rerun",
            body={},
            expected_statuses=(201,),
        )
    except GitHubApiError:
        unconfirmed = Report(
            run=run,
            stage=stage,
            reason_code="RERUN_API_UNCONFIRMED",
            decision="RERUN_REQUEST_UNCONFIRMED",
            requested_as_of_date=requested_date,
            twse_source_date=twse_date,
            tpex_source_date=tpex_date,
        )
        _ = _persist_report(
            client,
            repository,
            unconfirmed,
            issue=persisted,
            close=False,
        )
        _write_summary(summary_path, unconfirmed, repository)
        raise
    requested = Report(
        run=run,
        stage=stage,
        reason_code=reason_code,
        decision="RERUN_REQUESTED",
        requested_as_of_date=requested_date,
        twse_source_date=twse_date,
        tpex_source_date=tpex_date,
    )
    persisted = _persist_report(
        client,
        repository,
        requested,
        issue=persisted,
        close=False,
    )
    _write_summary(summary_path, requested, repository)
    return _result(run, decision="RERUN_REQUESTED", issue=persisted, rerun_requested=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report and boundedly rerun trusted daily pipeline failures.",
    )
    event_source = parser.add_mutually_exclusive_group()
    event_source.add_argument("--event-path", type=Path)
    event_source.add_argument("--event-json")
    parser.add_argument("--repository")
    return parser


def _load_event(arguments: argparse.Namespace) -> Mapping[str, Any]:
    raw_event = cast(str | None, arguments.event_json)
    if raw_event is None:
        event_path = cast(Path | None, arguments.event_path)
        if event_path is None:
            environment_path = os.environ.get("GITHUB_EVENT_PATH")
            if not environment_path:
                raise RecoveryError("MISSING_GITHUB_EVENT_PATH")
            event_path = Path(environment_path)
        try:
            raw_bytes = event_path.read_bytes()
        except OSError as error:
            raise RecoveryError("UNREADABLE_GITHUB_EVENT") from error
        if len(raw_bytes) > MAX_API_RESPONSE_BYTES:
            raise RecoveryError("GITHUB_EVENT_TOO_LARGE")
        try:
            raw_event = raw_bytes.decode("utf-8")
        except UnicodeDecodeError as error:
            raise RecoveryError("INVALID_GITHUB_EVENT") from error
    elif len(raw_event.encode("utf-8")) > MAX_API_RESPONSE_BYTES:
        raise RecoveryError("GITHUB_EVENT_TOO_LARGE")
    try:
        payload = json.loads(raw_event)
    except json.JSONDecodeError as error:
        raise RecoveryError("INVALID_GITHUB_EVENT") from error
    return _mapping(payload, "INVALID_GITHUB_EVENT")


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    summary_path_value = os.environ.get("GITHUB_STEP_SUMMARY")
    summary_path = Path(summary_path_value) if summary_path_value else None
    try:
        repository = cast(str | None, arguments.repository) or os.environ.get(
            "GITHUB_REPOSITORY",
            "",
        )
        event = _load_event(arguments)
        client = GitHubApiClient(
            token=os.environ.get("GITHUB_TOKEN", ""),
            api_url=os.environ.get("GITHUB_API_URL", "https://api.github.com"),
        )
        result = process_workflow_run(
            event,
            client=client,
            repository=repository,
            summary_path=summary_path,
        )
    except RecoveryError:
        if summary_path is not None:
            summary_path.parent.mkdir(parents=True, exist_ok=True)
            with summary_path.open("a", encoding="utf-8", newline="\n") as stream:
                _ = stream.write(
                    "## Daily pipeline recovery\n\n"
                    "- Decision: `FAILED_CLOSED`\n"
                    "- No workflow rerun was requested.\n"
                )
        print("::error::Daily pipeline recovery failed closed.", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "attempt": result.attempt,
                "decision": result.decision,
                "issue_number": result.issue_number,
                "rerun_requested": result.rerun_requested,
                "run_id": result.run_id,
                "workflow": result.workflow,
            },
            ensure_ascii=True,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
