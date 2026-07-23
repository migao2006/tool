from __future__ import annotations

import io
import json
from collections import deque
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from scripts.recover_daily_pipeline import (
    GitHubApiClient,
    GitHubApiError,
    RecoveryError,
    _StripCrossOriginAuthorization,
    process_workflow_run,
)


REPOSITORY = "migao2006/tool"
RUN_ID = 123456
CURRENT_SHA = "a" * 40
NEW_SHA = "b" * 40
IMPORT_NAME = "Import market data"
IMPORT_PATH = ".github/workflows/import-market-data.yml"
DAILY_NAME = "Daily research model"
DAILY_PATH = ".github/workflows/daily-research-model.yml"


def _workflow_run(
    *,
    name: str = IMPORT_NAME,
    path: str = IMPORT_PATH,
    conclusion: str = "failure",
    attempt: int = 1,
    sha: str = CURRENT_SHA,
) -> dict[str, Any]:
    return {
        "id": RUN_ID,
        "run_attempt": attempt,
        "status": "completed",
        "conclusion": conclusion,
        "name": name,
        "path": path,
        "event": "schedule",
        "head_branch": "main",
        "head_sha": sha,
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
        # These values are deliberately untrusted. Reports must construct their own URL.
        "html_url": "https://attacker.invalid/run?token=TOP_SECRET",
    }


def _event(**run_overrides: Any) -> dict[str, Any]:
    run = _workflow_run(**run_overrides)
    return {
        "action": "completed",
        "repository": {"full_name": REPOSITORY},
        "workflow_run": run,
    }


def _artifact_payload(
    *,
    status: str = "DEFERRED",
    reason_code: str = "SOURCE_MARKET_DATE_MISMATCH",
    requested_as_of_date: str | None = "2026-07-23",
    twse_source_date: str | None = "2026-07-22",
    tpex_source_date: str | None = "2026-07-23",
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "status": status,
        "reason_code": reason_code,
    }
    if requested_as_of_date is not None:
        payload["requested_as_of_date"] = requested_as_of_date
    if twse_source_date is not None:
        payload["twse_source_date"] = twse_source_date
    if tpex_source_date is not None:
        payload["tpex_source_date"] = tpex_source_date
    payload.update(extra)
    return payload


def _artifact_zip(payload: dict[str, Any], *, filename: str = "import-market-data-result.json") -> bytes:
    buffer = io.BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr(filename, json.dumps(payload))
    return buffer.getvalue()


class FakeGitHubClient:
    def __init__(
        self,
        *,
        run: dict[str, Any],
        branch_sha: str = CURRENT_SHA,
        jobs: list[dict[str, Any]] | None = None,
        issues: list[dict[str, Any]] | None = None,
        artifact_payload: dict[str, Any] | None = None,
    ) -> None:
        self.run_reads: deque[dict[str, Any]] = deque([run])
        self.branch_reads: deque[str] = deque([branch_sha])
        self.jobs = jobs or [{"name": "import", "conclusion": "failure"}]
        self.issues = issues or []
        self.artifact_payload = artifact_payload
        self.calls: list[tuple[str, str, dict[str, Any] | None]] = []
        self.fail_issue_write = False
        self.rerun_status = 201
        self.issue_number = 909
        self._page_overrides: dict[int, list[dict[str, Any]]] = {}

    def set_run_reads(self, *runs: dict[str, Any]) -> None:
        self.run_reads = deque(runs)

    def set_branch_reads(self, *shas: str) -> None:
        self.branch_reads = deque(shas)

    def set_issue_pages(self, **pages: list[dict[str, Any]]) -> None:
        self._page_overrides = {int(page): values for page, values in pages.items()}

    def request_json(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        expected_statuses: tuple[int, ...] = (200,),
    ) -> Any:
        self.calls.append((method, path, body))
        if method == "GET" and path == f"/repos/{REPOSITORY}/actions/runs/{RUN_ID}":
            if len(self.run_reads) > 1:
                return self.run_reads.popleft()
            return self.run_reads[0]
        if method == "GET" and path == f"/repos/{REPOSITORY}":
            return {"full_name": REPOSITORY, "default_branch": "main"}
        if method == "GET" and path == f"/repos/{REPOSITORY}/branches/main":
            sha = self.branch_reads.popleft() if len(self.branch_reads) > 1 else self.branch_reads[0]
            return {"name": "main", "commit": {"sha": sha}}
        if method == "GET" and "/attempts/" in path and "/jobs?" in path:
            page = int(path.rsplit("page=", 1)[1])
            return {"jobs": self.jobs if page == 1 else []}
        if method == "GET" and path.startswith(f"/repos/{REPOSITORY}/issues?"):
            page = int(path.rsplit("page=", 1)[1])
            if self._page_overrides:
                return self._page_overrides.get(page, [])
            return self.issues if page == 1 else []
        if method == "GET" and path.startswith(
            f"/repos/{REPOSITORY}/actions/runs/{RUN_ID}/artifacts?"
        ):
            if self.artifact_payload is None:
                return {"artifacts": []}
            attempt = self.run_reads[0]["run_attempt"]
            return {
                "artifacts": [
                    {
                        "id": 701,
                        "name": f"import-market-data-result-{RUN_ID}-{attempt}",
                        "expired": False,
                    }
                ]
            }
        if method == "POST" and path == f"/repos/{REPOSITORY}/issues":
            if self.fail_issue_write:
                raise GitHubApiError("ISSUE_WRITE_FAILED")
            return {"number": self.issue_number, "state": "open"}
        if method == "PATCH" and path.startswith(f"/repos/{REPOSITORY}/issues/"):
            if self.fail_issue_write:
                raise GitHubApiError("ISSUE_WRITE_FAILED")
            assert body is not None
            return {"number": int(path.rsplit("/", 1)[1]), "state": body.get("state", "open")}
        if method == "POST" and path == f"/repos/{REPOSITORY}/actions/runs/{RUN_ID}/rerun":
            if self.rerun_status not in expected_statuses:
                raise GitHubApiError("UNEXPECTED_HTTP_STATUS")
            return None
        raise AssertionError(f"Unexpected API call: {method} {path}")

    def request_bytes(
        self,
        method: str,
        path: str,
        *,
        expected_statuses: tuple[int, ...] = (200,),
        maximum_bytes: int,
    ) -> bytes:
        self.calls.append((method, path, None))
        assert maximum_bytes <= 65536
        assert method == "GET"
        assert path == f"/repos/{REPOSITORY}/actions/artifacts/701/zip"
        assert self.artifact_payload is not None
        return _artifact_zip(self.artifact_payload)


def _client_for(
    event: dict[str, Any],
    *,
    branch_sha: str = CURRENT_SHA,
    jobs: list[dict[str, Any]] | None = None,
    issues: list[dict[str, Any]] | None = None,
    artifact_payload: dict[str, Any] | None = None,
) -> FakeGitHubClient:
    return FakeGitHubClient(
        run=dict(event["workflow_run"]),
        branch_sha=branch_sha,
        jobs=jobs,
        issues=issues,
        artifact_payload=artifact_payload,
    )


def _call_body(call: tuple[str, str, dict[str, Any] | None]) -> dict[str, Any]:
    body = call[2]
    assert body is not None
    return body


def _recovery_issue(
    number: int,
    *,
    state: str,
    body: str,
) -> dict[str, Any]:
    return {
        "number": number,
        "state": state,
        "body": body,
        "user": {"login": "github-actions[bot]", "type": "Bot"},
        "performed_via_github_app": {"slug": "github-actions"},
    }


@pytest.mark.parametrize(
    ("event_change", "run_change"),
    [
        ({"action": "requested"}, {}),
        ({"repository": {"full_name": "attacker/fork"}}, {}),
        ({}, {"repository": {"full_name": "attacker/fork"}}),
        ({}, {"head_repository": {"full_name": "attacker/fork"}}),
        ({}, {"head_branch": "feature"}),
        ({}, {"name": "Attacker workflow"}),
        ({}, {"path": ".github/workflows/attacker.yml"}),
        ({}, {"id": 0}),
        ({}, {"run_attempt": 0}),
        ({}, {"head_sha": "not-a-sha"}),
    ],
)
def test_rejects_untrusted_event_before_any_api_write(
    event_change: dict[str, Any],
    run_change: dict[str, Any],
) -> None:
    event = _event()
    event.update(event_change)
    event["workflow_run"].update(run_change)
    client = _client_for(_event(), artifact_payload=_artifact_payload())

    with pytest.raises(RecoveryError):
        process_workflow_run(event, client=client, repository=REPOSITORY, sleep=lambda _: None)

    assert client.calls == []


def test_server_state_must_match_completed_event() -> None:
    event = _event()
    server = dict(event["workflow_run"], status="queued", conclusion=None, run_attempt=2)
    client = FakeGitHubClient(run=server, artifact_payload=_artifact_payload())

    result = process_workflow_run(
        event,
        client=client,
        repository=REPOSITORY,
        sleep=lambda _: None,
    )

    assert result.decision == "STATE_CHANGED"
    assert not any(method != "GET" for method, _, _ in client.calls)


def test_superseded_sha_is_reported_and_closed_without_rerun(tmp_path: Path) -> None:
    event = _event()
    client = _client_for(event, branch_sha=NEW_SHA, artifact_payload=_artifact_payload())
    summary = tmp_path / "summary.md"

    result = process_workflow_run(
        event,
        client=client,
        repository=REPOSITORY,
        summary_path=summary,
        sleep=lambda _: pytest.fail("superseded runs must not sleep"),
    )

    assert result.decision == "SUPERSEDED"
    assert result.rerun_requested is False
    assert [call[0] for call in client.calls].count("POST") == 1
    issue_create = next(call for call in client.calls if call[:2] == ("POST", f"/repos/{REPOSITORY}/issues"))
    assert "SUPERSEDED" in _call_body(issue_create)["body"]
    assert f"<!-- daily-pipeline-recovery:run-id={RUN_ID} -->" in _call_body(issue_create)["body"]
    close = next(call for call in client.calls if call[0] == "PATCH")
    assert _call_body(close)["state"] == "closed"
    assert "SUPERSEDED" in summary.read_text(encoding="utf-8")
    assert not any(path.endswith("/rerun") for _, path, _ in client.calls)


def test_import_mismatch_persists_issue_then_delays_and_requests_full_rerun(
    tmp_path: Path,
) -> None:
    event = _event()
    client = _client_for(event, artifact_payload=_artifact_payload())
    delays: list[int] = []
    summary = tmp_path / "summary.md"

    result = process_workflow_run(
        event,
        client=client,
        repository=REPOSITORY,
        summary_path=summary,
        sleep=delays.append,
    )

    assert result.decision == "RERUN_REQUESTED"
    assert result.rerun_requested is True
    assert delays == [900]
    issue_index = next(
        index
        for index, call in enumerate(client.calls)
        if call[:2] == ("POST", f"/repos/{REPOSITORY}/issues")
    )
    rerun_index = next(index for index, call in enumerate(client.calls) if call[1].endswith("/rerun"))
    assert issue_index < rerun_index
    rerun = client.calls[rerun_index]
    assert rerun == (
        "POST",
        f"/repos/{REPOSITORY}/actions/runs/{RUN_ID}/rerun",
        {},
    )
    body = _call_body(client.calls[issue_index])["body"]
    assert "SOURCE_MARKET_DATE_MISMATCH" in body
    assert "2026-07-22" in body
    assert "2026-07-23" in body
    assert "RECONCILE_LATEST_VALID" in body
    assert "RERUN_REQUESTED" in summary.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("payload", "decision"),
    [
        (_artifact_payload(status="FAIL", reason_code="IMPORT_FAILED"), "NON_RETRYABLE"),
        (
            _artifact_payload(
                status="PASS",
                reason_code="IMPORT_COMPLETED",
                as_of_date="2026-07-20",
                twse_source_date="2026-07-20",
                tpex_source_date="2026-07-20",
            ),
            "NON_RETRYABLE",
        ),
        (
            _artifact_payload(twse_source_date="not-a-date"),
            "UNVERIFIED_IMPORT_RESULT",
        ),
        (
            _artifact_payload(requested_as_of_date=None),
            "UNVERIFIED_IMPORT_RESULT",
        ),
        (
            _artifact_payload(tpex_source_date=None),
            "UNVERIFIED_IMPORT_RESULT",
        ),
        (
            _artifact_payload(extra_field="https://attacker.invalid/token=TOP_SECRET"),
            "UNVERIFIED_IMPORT_RESULT",
        ),
    ],
)
def test_import_permanent_or_invalid_results_are_reported_but_not_retried(
    payload: dict[str, Any],
    decision: str,
) -> None:
    event = _event()
    client = _client_for(event, artifact_payload=payload)

    result = process_workflow_run(
        event,
        client=client,
        repository=REPOSITORY,
        sleep=lambda _: pytest.fail("ineligible import must not sleep"),
    )

    assert result.decision == decision
    assert not any(path.endswith("/rerun") for _, path, _ in client.calls)


def test_verified_permanent_import_reason_is_preserved_in_report() -> None:
    event = _event()
    client = _client_for(
        event,
        artifact_payload=_artifact_payload(
            status="FAIL",
            reason_code="SOURCE_DATA_STALE",
        ),
    )

    result = process_workflow_run(
        event,
        client=client,
        repository=REPOSITORY,
        sleep=lambda _: pytest.fail("permanent import must not sleep"),
    )

    assert result.decision == "NON_RETRYABLE"
    issue_create = next(
        call
        for call in client.calls
        if call[:2] == ("POST", f"/repos/{REPOSITORY}/issues")
    )
    issue_body = issue_create[2]
    assert issue_body is not None
    assert "SOURCE_DATA_STALE" in issue_body["body"]


def test_missing_import_artifact_is_fail_closed_and_reported() -> None:
    event = _event()
    client = _client_for(event, artifact_payload=None)

    result = process_workflow_run(
        event,
        client=client,
        repository=REPOSITORY,
        sleep=lambda _: pytest.fail("missing evidence must not sleep"),
    )

    assert result.decision == "UNVERIFIED_IMPORT_RESULT"
    assert any(call[:2] == ("POST", f"/repos/{REPOSITORY}/issues") for call in client.calls)
    assert not any(path.endswith("/rerun") for _, path, _ in client.calls)


@pytest.mark.parametrize(
    ("name", "path", "attempt", "conclusion", "expected_delay", "decision"),
    [
        (IMPORT_NAME, IMPORT_PATH, 2, "failure", None, "EXHAUSTED"),
        (DAILY_NAME, DAILY_PATH, 1, "failure", 300, "RERUN_REQUESTED"),
        (DAILY_NAME, DAILY_PATH, 2, "timed_out", 900, "RERUN_REQUESTED"),
        (DAILY_NAME, DAILY_PATH, 3, "failure", None, "EXHAUSTED"),
    ],
)
def test_retry_limits_and_delays(
    name: str,
    path: str,
    attempt: int,
    conclusion: str,
    expected_delay: int | None,
    decision: str,
) -> None:
    event = _event(name=name, path=path, attempt=attempt, conclusion=conclusion)
    jobs = [{"name": "resolve", "conclusion": conclusion}] if name == DAILY_NAME else None
    artifact = _artifact_payload() if name == IMPORT_NAME else None
    client = _client_for(event, jobs=jobs, artifact_payload=artifact)
    delays: list[int] = []

    result = process_workflow_run(
        event,
        client=client,
        repository=REPOSITORY,
        sleep=delays.append,
    )

    assert result.decision == decision
    assert delays == ([] if expected_delay is None else [expected_delay])
    assert result.rerun_requested is (expected_delay is not None)


@pytest.mark.parametrize(
    "conclusion",
    ["cancelled", "skipped", "action_required", "neutral", "stale", "startup_failure"],
)
def test_daily_non_failure_conclusions_never_rerun(conclusion: str) -> None:
    event = _event(name=DAILY_NAME, path=DAILY_PATH, conclusion=conclusion)
    client = _client_for(
        event,
        jobs=[{"name": "resolve", "conclusion": conclusion}],
    )

    result = process_workflow_run(
        event,
        client=client,
        repository=REPOSITORY,
        sleep=lambda _: pytest.fail("ineligible conclusion must not sleep"),
    )

    assert result.decision == "INELIGIBLE"
    assert not any(path.endswith("/rerun") for _, path, _ in client.calls)


def test_issue_lookup_paginates_skips_pull_requests_and_reopens_deduplicated_issue() -> None:
    event = _event(name=DAILY_NAME, path=DAILY_PATH)
    marker = f"<!-- daily-pipeline-recovery:run-id={RUN_ID} -->"
    client = _client_for(event, jobs=[{"name": "resolve", "conclusion": "failure"}])
    client.set_issue_pages(
        **{
            "1": [
                {
                    "number": index + 1,
                    "state": "closed",
                    "body": marker if index == 0 else "",
                    "pull_request": {"url": "https://api.github.com/pulls/1"},
                }
                for index in range(10)
            ],
            "2": [_recovery_issue(808, state="closed", body=marker)],
        }
    )

    result = process_workflow_run(
        event,
        client=client,
        repository=REPOSITORY,
        sleep=lambda _: None,
    )

    assert result.issue_number == 808
    assert not any(call[:2] == ("POST", f"/repos/{REPOSITORY}/issues") for call in client.calls)
    patches = [call for call in client.calls if call[:2] == ("PATCH", f"/repos/{REPOSITORY}/issues/808")]
    assert patches
    assert _call_body(patches[0])["state"] == "open"
    issue_queries = [
        path for method, path, _ in client.calls if method == "GET" and "/issues?" in path
    ]
    assert any("page=2" in path for path in issue_queries)
    assert all("creator=github-actions%5Bbot%5D" in path for path in issue_queries)
    assert all("per_page=10" in path for path in issue_queries)


def test_success_updates_and_closes_existing_issue() -> None:
    event = _event(name=DAILY_NAME, path=DAILY_PATH, conclusion="success", attempt=2)
    marker = f"<!-- daily-pipeline-recovery:run-id={RUN_ID} -->"
    client = _client_for(
        event,
        issues=[_recovery_issue(808, state="open", body=marker)],
    )

    result = process_workflow_run(
        event,
        client=client,
        repository=REPOSITORY,
        sleep=lambda _: pytest.fail("success must not sleep"),
    )

    assert result.decision == "RECOVERED"
    assert result.issue_number == 808
    patch = next(call for call in client.calls if call[0] == "PATCH")
    assert _call_body(patch)["state"] == "closed"
    assert "RECOVERED" in _call_body(patch)["body"]
    assert not any(path.endswith("/rerun") for _, path, _ in client.calls)


def test_forged_or_nonleading_markers_cannot_hijack_recovery_issue() -> None:
    event = _event(name=DAILY_NAME, path=DAILY_PATH)
    marker = f"<!-- daily-pipeline-recovery:run-id={RUN_ID} -->"
    client = _client_for(
        event,
        jobs=[{"name": "resolve", "conclusion": "failure"}],
        issues=[
            {
                "number": 1,
                "state": "open",
                "body": marker,
                "user": {"login": "external-user", "type": "User"},
            },
            _recovery_issue(
                2,
                state="open",
                body=f"quoted marker\n{marker}",
            ),
            _recovery_issue(808, state="open", body=f"{marker}\ntrusted"),
        ],
    )

    result = process_workflow_run(
        event,
        client=client,
        repository=REPOSITORY,
        sleep=lambda _: None,
    )

    assert result.issue_number == 808
    assert any(
        call[:2] == ("PATCH", f"/repos/{REPOSITORY}/issues/808")
        for call in client.calls
    )
    assert not any(
        call[:2] == ("PATCH", f"/repos/{REPOSITORY}/issues/1")
        for call in client.calls
    )
    assert not any(
        call[:2] == ("PATCH", f"/repos/{REPOSITORY}/issues/2")
        for call in client.calls
    )


def test_multiple_trusted_recovery_issues_fail_closed() -> None:
    event = _event(name=DAILY_NAME, path=DAILY_PATH)
    marker = f"<!-- daily-pipeline-recovery:run-id={RUN_ID} -->"
    client = _client_for(
        event,
        jobs=[{"name": "resolve", "conclusion": "failure"}],
        issues=[
            _recovery_issue(808, state="open", body=marker),
            _recovery_issue(809, state="closed", body=marker),
        ],
    )

    with pytest.raises(RecoveryError, match="DUPLICATE_RECOVERY_ISSUES"):
        process_workflow_run(
            event,
            client=client,
            repository=REPOSITORY,
            sleep=lambda _: None,
        )

    assert not any(
        method in {"POST", "PATCH"} for method, _, _ in client.calls
    )


def test_issue_write_failure_prevents_sleep_and_rerun() -> None:
    event = _event(name=DAILY_NAME, path=DAILY_PATH)
    client = _client_for(event, jobs=[{"name": "resolve", "conclusion": "failure"}])
    client.fail_issue_write = True
    delays: list[int] = []

    with pytest.raises(GitHubApiError):
        process_workflow_run(
            event,
            client=client,
            repository=REPOSITORY,
            sleep=delays.append,
        )

    assert delays == []
    assert not any(path.endswith("/rerun") for _, path, _ in client.calls)


def test_state_change_after_delay_is_reported_without_rerun() -> None:
    event = _event(name=DAILY_NAME, path=DAILY_PATH)
    initial = dict(event["workflow_run"])
    changed = dict(initial, status="queued", conclusion=None, run_attempt=2)
    client = _client_for(event, jobs=[{"name": "resolve", "conclusion": "failure"}])
    client.set_run_reads(initial, changed)
    delays: list[int] = []

    result = process_workflow_run(
        event,
        client=client,
        repository=REPOSITORY,
        sleep=delays.append,
    )

    assert delays == [300]
    assert result.decision == "STATE_CHANGED"
    assert not any(path.endswith("/rerun") for _, path, _ in client.calls)


def test_main_sha_change_after_delay_marks_superseded_without_rerun() -> None:
    event = _event(name=DAILY_NAME, path=DAILY_PATH)
    client = _client_for(event, jobs=[{"name": "resolve", "conclusion": "failure"}])
    client.set_branch_reads(CURRENT_SHA, NEW_SHA)

    result = process_workflow_run(
        event,
        client=client,
        repository=REPOSITORY,
        sleep=lambda _: None,
    )

    assert result.decision == "SUPERSEDED"
    assert not any(path.endswith("/rerun") for _, path, _ in client.calls)
    assert any(
        call[0] == "PATCH" and _call_body(call)["state"] == "closed" for call in client.calls
    )


def test_malicious_event_artifact_and_job_content_never_reaches_issue_or_summary(
    tmp_path: Path,
) -> None:
    secret = "TOP_SECRET_TOKEN"
    event = _event()
    event["workflow_run"]["display_title"] = secret
    event["sender"] = {"login": secret}
    client = _client_for(
        event,
        jobs=[{"name": f"evil-{secret}", "conclusion": "failure"}],
        artifact_payload=_artifact_payload(message=secret),
    )
    summary = tmp_path / "summary.md"

    result = process_workflow_run(
        event,
        client=client,
        repository=REPOSITORY,
        summary_path=summary,
        sleep=lambda _: pytest.fail("invalid evidence must not sleep"),
    )

    assert result.decision == "UNVERIFIED_IMPORT_RESULT"
    written_bodies = [
        call[2]["body"]
        for call in client.calls
        if call[0] in {"POST", "PATCH"} and call[2] and "body" in call[2]
    ]
    assert written_bodies
    assert all(secret not in body for body in written_bodies)
    assert all("attacker.invalid" not in body for body in written_bodies)
    summary_text = summary.read_text(encoding="utf-8")
    assert secret not in summary_text
    assert "attacker.invalid" not in summary_text
    assert "Stage: `UNKNOWN`" in written_bodies[0]


def test_non_201_rerun_response_fails_after_persistent_issue() -> None:
    event = _event(name=DAILY_NAME, path=DAILY_PATH)
    client = _client_for(event, jobs=[{"name": "resolve", "conclusion": "failure"}])
    client.rerun_status = 202

    with pytest.raises(GitHubApiError):
        process_workflow_run(
            event,
            client=client,
            repository=REPOSITORY,
            sleep=lambda _: None,
        )

    issue_index = next(
        index
        for index, call in enumerate(client.calls)
        if call[:2] == ("POST", f"/repos/{REPOSITORY}/issues")
    )
    rerun_index = next(index for index, call in enumerate(client.calls) if call[1].endswith("/rerun"))
    assert issue_index < rerun_index
    unconfirmed = [
        call
        for call in client.calls
        if call[0] == "PATCH"
        and "RERUN_REQUEST_UNCONFIRMED" in _call_body(call).get("body", "")
    ]
    assert unconfirmed
    assert _call_body(unconfirmed[-1])["state"] == "open"


def test_mutating_request_timeout_is_not_blindly_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[Any] = []

    def fake_urlopen(request: Any, *, timeout: float) -> Any:
        calls.append((request, timeout))
        raise URLError("timed out")

    monkeypatch.setattr("scripts.recover_daily_pipeline.urlopen", fake_urlopen)
    client = GitHubApiClient(
        token="redacted-token",
        api_url="https://api.github.com",
        timeout_seconds=5,
    )

    with pytest.raises(GitHubApiError):
        client.request_json(
            "POST",
            f"/repos/{REPOSITORY}/actions/runs/{RUN_ID}/rerun",
            body={},
            expected_statuses=(201,),
        )

    assert len(calls) == 1
    request = calls[0][0]
    assert request.headers["X-github-api-version"] == "2026-03-10"
    assert request.headers["Authorization"] == "Bearer redacted-token"


def test_cross_origin_artifact_redirect_strips_github_authorization() -> None:
    request = Request(
        "https://api.github.com/repos/migao2006/tool/actions/artifacts/701/zip",
        headers={
            "Authorization": "Bearer redacted-token",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "alpha-lens-daily-pipeline-recovery",
        },
    )

    redirected = _StripCrossOriginAuthorization().redirect_request(
        request,
        None,
        302,
        "Found",
        {},
        "https://results-receiver.actions.githubusercontent.com/artifact.zip",
    )

    assert redirected is not None
    assert redirected.get_header("Authorization") is None
    assert redirected.get_header("X-GitHub-Api-Version") is None
