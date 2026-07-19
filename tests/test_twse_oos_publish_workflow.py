from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/publish-twse-oos-research-snapshot.yml"


def test_publish_workflow_passes_verified_prepared_artifact_sidecar() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "--input inputs/prepared/twse-prepared-research.parquet" in workflow
    assert (
        "--input-audit inputs/prepared/twse-prepared-research-audit.json" in workflow
    )
