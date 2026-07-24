from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260724085021_publish_research_market_evidence_atomically.sql"
)
ROLLBACK = (
    ROOT
    / "supabase"
    / "snippets"
    / "rollback_research_market_evidence_publisher.sql"
)
VALIDATION = (
    ROOT
    / "supabase"
    / "snippets"
    / "validate_research_market_evidence_publisher.sql"
)


def test_market_evidence_publisher_is_additive_atomic_and_service_only() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    compact = " ".join(sql.split())

    assert "p_market_prediction jsonb" in sql
    assert "insert into market_data.market_predictions" in sql
    assert "RESEARCH_MARKET_EVIDENCE_ROW_WITHOUT_PUBLICATION" in sql
    assert "RESEARCH_MARKET_EVIDENCE_IMMUTABILITY_CONFLICT" in sql
    assert "RESEARCH_MARKET_EVIDENCE_ATOMIC_COUNT_MISMATCH" in sql
    assert "RESEARCH_EVALUATED_CANDIDATE_COUNT_MISMATCH" in sql
    assert "set decision = 'CANDIDATE'" in sql
    assert "or v_market_exposure_cap is null" in sql
    assert "or v_training_end_date is null" in sql
    assert (
        "market_data.publish_research_prediction_snapshot( "
        "p_run, p_stock_predictions )"
    ) in compact
    assert "grant execute on function market_data.publish_research_prediction_snapshot(" in sql
    assert ") to service_role;" in sql
    assert "drop table" not in sql.lower()
    assert compact.count("update market_data.stock_predictions as stored") == 1
    assert (
        "where stored.prediction_run_id = v_prediction_run_id "
        "and stored.security_id = published.security_id "
        "and published.decision_policy_status = 'EVALUATED' "
        "and published.decision = 'CANDIDATE'"
    ) in compact
    assert "v_persisted_candidate_count <> v_candidate_count" in compact


def test_market_evidence_publisher_has_rollback_and_grant_validation() -> None:
    rollback = ROLLBACK.read_text(encoding="utf-8")
    validation = VALIDATION.read_text(encoding="utf-8")

    assert "drop function market_data.publish_research_prediction_snapshot(" in rollback
    assert "jsonb,\n  jsonb,\n  jsonb" in rollback
    assert "has_function_privilege" in validation
    assert "service_role" in validation
    assert "authenticated" in validation
