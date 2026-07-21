from datetime import date

from scripts.check_data_apis import build_report
from src.data.providers.errors import ProviderHttpError, ProviderPayloadError
from src.data.providers.health import ProviderProbeResult, run_live_probes


class _FailingAlphaVantageClient:
    def fetch_macro(self, *_args, **_kwargs):
        raise ProviderHttpError(403, "https://api.example.test?api_key=REDACTED")


class _RateLimitedAlphaVantageClient:
    def fetch_macro(self, *_args, **_kwargs):
        raise ProviderPayloadError(
            "ALPHA_VANTAGE_RATE_LIMITED",
            "provider request quota is temporarily exhausted",
        )


def test_live_probe_reports_only_safe_http_status() -> None:
    results = run_live_probes(
        {"ALPHA_VANTAGE": _FailingAlphaVantageClient()},
        as_of_date=date(2026, 7, 18),
    )

    assert len(results) == 1
    assert results[0].status == "FAIL"
    assert results[0].reason_code == "PROVIDER_HTTP_ERROR"
    assert results[0].http_status == 403
    assert "api_key" not in str(results[0].to_dict())


def test_live_probe_reports_optional_rate_limit_as_degraded() -> None:
    results = run_live_probes(
        {"ALPHA_VANTAGE": _RateLimitedAlphaVantageClient()},
        as_of_date=date(2026, 7, 18),
    )

    assert len(results) == 1
    assert results[0].status == "DEGRADED"
    assert results[0].reason_code == "ALPHA_VANTAGE_RATE_LIMITED"


def test_readiness_report_keeps_degraded_provider_research_only(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.check_data_apis.run_live_probes",
        lambda *_args, **_kwargs: (
            ProviderProbeResult(
                provider="ALPHA_VANTAGE",
                status="DEGRADED",
                reason_code="ALPHA_VANTAGE_RATE_LIMITED",
            ),
        ),
    )

    report, exit_code = build_report(live=True, as_of_date=date(2026, 7, 18))

    assert report["status"] == "RESEARCH_ONLY"
    assert exit_code == 0
