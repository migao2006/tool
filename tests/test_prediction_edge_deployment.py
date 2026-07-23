from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_edge_smoke_requires_pages_and_checks_every_allowlisted_origin() -> None:
    smoke = (ROOT / ".github/scripts/smoke-prediction-snapshot.mjs").read_text(
        encoding="utf-8"
    )

    assert '"GITHUB_REPOSITORY_OWNER"' in smoke
    assert "requiredPagesOrigin" in smoke
    assert "allowedOrigins.includes(requiredPagesOrigin)" in smoke
    assert "for (const uiOrigin of allowedOrigins)" in smoke
    assert (
        'await readSnapshot("horizon=5&market=TWSE", "TWSE", uiOrigin)' in smoke
    )
