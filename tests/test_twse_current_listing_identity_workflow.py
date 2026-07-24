from pathlib import Path


WORKFLOW = Path(".github/workflows/import-security-snapshot.yml")


def test_security_snapshot_workflow_also_preserves_listing_identity_evidence() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "scripts.import_security_snapshot" in workflow
    assert "scripts.import_twse_current_listing_identity" in workflow
    assert "current-listing-identity-summary.json" in workflow
    assert workflow.count("SUPABASE_SERVICE_ROLE_KEY: ${{") == 2
    assert "args+=(--dry-run)" in workflow
    assert "blank resolves each selected venue independently" in workflow
    assert "fail-fast: false" in workflow
    assert "args=(--market \"$MARKET\")" in workflow
    assert "matrix.market" in workflow
    assert (
        "- name: Import unresolved current listing identity evidence\n"
        "        if: always() && matrix.market == 'TWSE'"
        in workflow
    )
    assert workflow.count("REQUESTED_SNAPSHOT_DATE: ${{ inputs.snapshot_date }}") == 1
