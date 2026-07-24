from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-prediction-edge-function.yml"


def test_edge_deploy_uses_management_api_bundling() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert workflow.count(
        "pnpm exec supabase functions deploy prediction-snapshot"
    ) == 2
    assert workflow.count("--use-api") == 2
