"""Local-only server for verifying the frontend against the real API contract."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from src.api import (
    DecisionGateOutput,
    ExcludedSecurityOutput,
    MarketOutput,
    PredictionSnapshotOutput,
    StockPredictionOutput,
)


ROOT = Path(__file__).resolve().parents[2]
AS_OF_DATE = date(2026, 7, 17)
DECISION_AT = datetime(2026, 7, 17, 16, 0, tzinfo=timezone(timedelta(hours=8)))
TRAINING_END_DATE = date(2026, 6, 30)
GATE_NAMES = (
    "data_quality_hard_gate",
    "tradability_gate",
    "liquidity_capacity_gate",
    "market_exposure_cap",
    "calibrated_direction_probabilities",
    "net_quantile_thresholds",
    "rank_eligibility",
    "position_capacity_limits",
)


def build_snapshot() -> dict[str, object]:
    gates = tuple(
        DecisionGateOutput(
            gate=name,
            passed=True,
            actual={"test_value": index + 1},
            threshold={"required": True},
            reason_code="PASS",
            source_date=AS_OF_DATE,
        )
        for index, name in enumerate(GATE_NAMES)
    )
    prediction = StockPredictionOutput(
        as_of_date=AS_OF_DATE,
        decision_at=DECISION_AT,
        symbol="TEST1",
        name="API 契約測試標的",
        market="LISTED",
        industry="TEST_INDUSTRY",
        horizon=5,
        rank_score=95.0,
        global_rank=1,
        global_rank_percentile=0.99,
        industry_rank=1,
        industry_rank_percentile=0.98,
        calibrated_p_up=0.65,
        calibrated_p_neutral=0.25,
        calibrated_p_down=0.10,
        calibration_version="direction-cal-v1",
        gross_q10=-0.02,
        gross_q50=0.02,
        gross_q90=0.05,
        net_q10=-0.03,
        net_q50=0.01,
        net_q90=0.03,
        interval_width=0.06,
        calibration_status="CALIBRATED:quantile-cal-v1",
        forecast_volatility=0.03,
        downside_risk=0.02,
        market_regime="UPTREND_NORMAL_VOL",
        market_exposure_cap=0.60,
        estimated_round_trip_cost=0.01,
        data_quality_status="PASS",
        decision="CANDIDATE",
        reason_codes=(),
        model_version="rank-5d-v1",
        feature_schema_hash="schema-sha256-v1",
        cost_profile_version="tw-stock-base-v1",
        training_end_date=TRAINING_END_DATE,
        source_dates={"daily_bars": AS_OF_DATE},
        latest_available_at=DECISION_AT,
        liquidity_bucket="LARGE_LIQUID",
        adv20=1_000_000_000.0,
        max_order_notional_ntd=10_000_000.0,
        max_single_position=0.10,
        max_industry_position=0.25,
        cost_profile="base_cost",
        previous_global_rank=3,
        previous_decision="WATCH",
        gates=gates,
    )
    return PredictionSnapshotOutput(
        as_of_date=AS_OF_DATE,
        decision_at=DECISION_AT,
        horizon=5,
        system_status="PASS",
        predictions=(prediction,),
        market=MarketOutput(
            as_of_date=AS_OF_DATE,
            decision_at=DECISION_AT,
            horizon=5,
            p_up=0.60,
            p_neutral=0.25,
            p_down=0.15,
            market_regime="UPTREND_NORMAL_VOL",
            forecast_market_volatility=0.18,
            market_exposure_cap=0.60,
            model_version="market-5d-v1",
            training_end_date=TRAINING_END_DATE,
        ),
        excluded=(
            ExcludedSecurityOutput(
                as_of_date=AS_OF_DATE,
                symbol="FAIL1",
                name="API 排除測試標的",
                market="OTC",
                horizon=5,
                reason_codes=("DATA_QUALITY_HARD_FAIL",),
                latest_available_at=DECISION_AT,
            ),
        ),
        model_version="rank-5d-v1",
        training_end_date=TRAINING_END_DATE,
        cost_profile_version="tw-stock-base-v1",
        validation={"ndcg_10": 0.42, "known_limitations": ["TEST_ONLY_FIXTURE"]},
    ).to_dict()


def build_research_snapshot() -> dict[str, object]:
    payload = build_snapshot()
    prediction = dict(payload["predictions"][0])
    prediction["symbol"] = "RESEARCH1"
    prediction["rank_score"] = 94.0
    prediction["global_rank"] = 2
    prediction["global_rank_percentile"] = 0.98
    prediction["calibrated_p_up"] = 0.62
    prediction["calibrated_p_neutral"] = 0.26
    prediction["calibrated_p_down"] = 0.12
    prediction["net_q50"] = 0.012
    prediction["net_q90"] = 0.04
    prediction["reason_codes"] = ["RESEARCH_OUTPUT"]
    for missing_field in (
        "name",
        "industry",
        "asset_type",
        "decision",
        "data_quality_status",
        "gross_q10",
        "net_q10",
        "liquidity_bucket",
        "max_single_position",
        "max_industry_position",
        "cost_profile",
        "previous_global_rank",
        "previous_decision",
        "gates",
    ):
        prediction.pop(missing_field, None)

    payload["system_status"] = "RESEARCH_ONLY"
    payload["predictions"] = [prediction]
    payload["watchlist"] = [dict(prediction)]
    payload["excluded"] = []
    payload["reason_codes"] = ["RESEARCH_OUTPUT"]
    payload["market"] = {
        "as_of_date": payload["as_of_date"],
        "decision_at": payload["decision_at"],
        "horizon": 5,
        "market_direction": {"p_up": 0.62},
        "market_regime": "SIDEWAYS",
    }
    return payload


def build_stale_oos_research_snapshot() -> dict[str, object]:
    """Mirror the stored OOS publisher: complete fields, all rows NO_TRADE."""

    payload = build_snapshot()
    prediction = dict(payload["predictions"][0])
    prediction.update(
        {
            "symbol": "OOS1",
            "name": "歷史研究標的",
            "rank_score": 97.0,
            "global_rank": 1,
            "global_rank_percentile": 0.97,
            "calibrated_p_up": 0.61,
            "calibrated_p_neutral": 0.27,
            "calibrated_p_down": 0.12,
            "net_q10": -0.024,
            "net_q50": 0.013,
            "net_q90": 0.046,
            "interval_width": 0.07,
            "decision": "NO_TRADE",
            "reason_codes": [
                "RESEARCH_ONLY_NO_FORMAL_DECISION_POLICY",
                "UNADJUSTED_PRICE_RESEARCH_ONLY",
                "FORMAL_LABEL_FACTORY_NOT_USED",
                "POINT_IN_TIME_IDENTITY_UNVERIFIED",
                "MARKET_EXPOSURE_NOT_AVAILABLE",
            ],
            "gates": [],
        }
    )
    payload["system_status"] = "RESEARCH_ONLY"
    payload["stale"] = True
    payload["predictions"] = [prediction]
    payload["watchlist"] = []
    payload["excluded"] = []
    payload["reason_codes"] = ["RESEARCH_ONLY", "STALE_PREDICTION_SNAPSHOT"]
    return payload


def build_gated_research_snapshot() -> dict[str, object]:
    """Expose a complete mixed gate set while remaining RESEARCH_ONLY."""

    payload = build_snapshot()
    prediction = dict(payload["predictions"][0])
    prediction.update(
        {
            "symbol": "GATED1",
            "name": "研究決策測試標的",
            "decision": "NO_TRADE",
            "data_quality_status": "WARN",
            "reason_codes": [
                "DATA_QUALITY_NOT_FORMALLY_VERIFIED",
                "FORMAL_TRADABILITY_INPUT_MISSING",
                "FORMAL_MARKET_EXPOSURE_INPUT_MISSING",
            ],
            "gates": [
                {
                    "gate": name,
                    "passed": name
                    in {
                        "liquidity_capacity_gate",
                        "calibrated_direction_probabilities",
                        "net_quantile_thresholds",
                        "rank_eligibility",
                    },
                    "actual": (
                        {"adv20_ntd": 1_000_000_000, "order_notional": 100_000}
                        if name == "liquidity_capacity_gate"
                        else "MISSING"
                        if name
                        in {
                            "tradability_gate",
                            "market_exposure_cap",
                            "position_capacity_limits",
                        }
                        else {"research_value": index + 1}
                    ),
                    "threshold": {"configured": True},
                    "reason_code": (
                        "PASS"
                        if name
                        in {
                            "liquidity_capacity_gate",
                            "calibrated_direction_probabilities",
                            "net_quantile_thresholds",
                            "rank_eligibility",
                        }
                        else "FORMAL_INPUT_MISSING"
                    ),
                    "source_date": (
                        AS_OF_DATE.isoformat()
                        if name
                        in {
                            "data_quality_hard_gate",
                            "liquidity_capacity_gate",
                            "calibrated_direction_probabilities",
                            "net_quantile_thresholds",
                            "rank_eligibility",
                        }
                        else None
                    ),
                }
                for index, name in enumerate(GATE_NAMES)
            ],
        }
    )
    payload["system_status"] = "RESEARCH_ONLY"
    payload["predictions"] = [prediction]
    payload["watchlist"] = []
    payload["excluded"] = []
    payload["reason_codes"] = ["RESEARCH_DECISION_POLICY_EXECUTED_FAIL_CLOSED"]
    return payload


class FixtureHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/api-invalid/prediction-snapshot":
            self._send(200, b"{invalid-json", "application/json; charset=utf-8")
            return
        if parsed.path == "/api-contract-error/prediction-snapshot":
            payload = build_snapshot()
            payload["predictions"][0]["global_rank"] = 0
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            self._send(200, body, "application/json; charset=utf-8")
            return
        if parsed.path == "/api-research/prediction-snapshot":
            body = json.dumps(
                build_research_snapshot(), ensure_ascii=False, allow_nan=False
            ).encode()
            self._send(200, body, "application/json; charset=utf-8")
            return
        if parsed.path == "/api-stale-oos-research/prediction-snapshot":
            body = json.dumps(
                build_stale_oos_research_snapshot(),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
            self._send(200, body, "application/json; charset=utf-8")
            return
        if parsed.path == "/api-gated-research/prediction-snapshot":
            body = json.dumps(
                build_gated_research_snapshot(),
                ensure_ascii=False,
                allow_nan=False,
            ).encode()
            self._send(200, body, "application/json; charset=utf-8")
            return
        if parsed.path == "/api-partial-gates/prediction-snapshot":
            payload = build_gated_research_snapshot()
            payload["predictions"][0]["gates"].pop()
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode()
            self._send(200, body, "application/json; charset=utf-8")
            return
        if parsed.path == "/api-conflict/prediction-snapshot":
            body = b'{"code":"MODEL_DATA_VERSION_CONFLICT"}'
            self._send(409, body, "application/json; charset=utf-8")
            return
        if parsed.path == "/api/prediction-snapshot":
            if parse_qs(parsed.query).get("horizon") != ["5"]:
                self._send(422, b'{"code":"INVALID_HORIZON"}', "application/json")
                return
            body = json.dumps(
                build_snapshot(), ensure_ascii=False, allow_nan=False
            ).encode()
            self._send(200, body, "application/json; charset=utf-8")
            return
        if parsed.path == "/contract-test":
            html = """<!doctype html><meta charset=\"utf-8\"><body>running</body>
<script type=\"module\">
import { normalizePredictionSnapshot } from '/src/data/prediction-contract.js?v=contract-test-4';
try {
  const response = await fetch('/api/prediction-snapshot?horizon=5');
  const snapshot = normalizePredictionSnapshot(await response.json(), 5);
  document.body.textContent = JSON.stringify({ok: true, status: snapshot.systemStatus});
} catch (error) {
  document.body.textContent = JSON.stringify({ok: false, name: error.name, message: error.message});
}
</script>"""
            self._send(200, html.encode(), "text/html; charset=utf-8")
            return
        if parsed.path in {"/", "/index.html"}:
            mode = parse_qs(parsed.query).get("api_mode", [""])[0]
            api_path = {
                "invalid-json": "api-invalid",
                "contract-error": "api-contract-error",
                "conflict": "api-conflict",
                "research": "api-research",
                "stale-oos-research": "api-stale-oos-research",
                "gated-research": "api-gated-research",
                "partial-gates": "api-partial-gates",
            }.get(mode, "api")
            html = (
                (ROOT / "index.html")
                .read_text(encoding="utf-8")
                .replace(
                    '<html lang="zh-Hant">',
                    f'<html lang="zh-Hant" data-prediction-api-base-url="/{api_path}/">',
                )
            )
            self._send(200, html.encode(), "text/html; charset=utf-8")
            return
        super().do_GET()

    def log_message(self, _format: str, *args: object) -> None:
        return


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4180)
    args = parser.parse_args()
    ThreadingHTTPServer(("127.0.0.1", args.port), FixtureHandler).serve_forever()


if __name__ == "__main__":
    main()
