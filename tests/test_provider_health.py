from datetime import date

from src.data.providers.errors import ProviderHttpError
from src.data.providers.health import run_live_probes


class _FailingFredClient:
    def observations(self, *_args, **_kwargs):
        raise ProviderHttpError(403, "https://api.example.test?api_key=REDACTED")


def test_live_probe_reports_only_safe_http_status() -> None:
    results = run_live_probes(
        {"FRED": _FailingFredClient()},
        as_of_date=date(2026, 7, 18),
    )

    assert len(results) == 1
    assert results[0].status == "FAIL"
    assert results[0].reason_code == "PROVIDER_HTTP_ERROR"
    assert results[0].http_status == 403
    assert "api_key" not in str(results[0].to_dict())
