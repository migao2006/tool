from __future__ import annotations

import json
from pathlib import Path

from scripts import build_twse_prepared_research_dataset as cli


def test_unsupported_horizon_fails_before_external_io_and_preserves_output(
    tmp_path: Path,
) -> None:
    output = tmp_path / "prepared.parquet"
    audit = tmp_path / "audit.json"
    output.write_bytes(b"previous verified artifact")

    exit_code = cli.main(
        [
            "--feature",
            str(tmp_path / "missing-feature.parquet"),
            "--feature-manifest",
            str(tmp_path / "missing-feature.json"),
            "--output",
            str(output),
            "--audit",
            str(audit),
            "--horizon",
            "3",
        ]
    )

    payload = json.loads(audit.read_text(encoding="utf-8"))
    assert exit_code == 1
    assert payload["reason_codes"] == ["UNSUPPORTED_HORIZON"]
    assert payload["system_status"] == "FAIL"
    assert output.read_bytes() == b"previous verified artifact"
    assert not list(tmp_path.glob("*.candidate"))
