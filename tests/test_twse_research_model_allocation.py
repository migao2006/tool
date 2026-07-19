from __future__ import annotations

# pyright: reportMissingTypeStubs=false, reportPrivateUsage=false

from datetime import date

import pandas as pd

from src.pipeline.twse_research_model_evaluation import (
    _column_values,
    _sample_ids,
)


def test_column_values_preserve_requested_positional_order() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["1101", "2317", "2330"],
            "decision_date": [
                date(2026, 1, 2),
                date(2026, 1, 3),
                date(2026, 1, 4),
            ],
            "net_alpha": [0.01, 0.02, 0.03],
            "unrelated": [object(), object(), object()],
        }
    )

    assert _column_values(frame, (2, 0, 2), "net_alpha") == [0.03, 0.01, 0.03]


def test_sample_ids_preserve_requested_positional_order_and_identity() -> None:
    frame = pd.DataFrame(
        {
            "symbol": ["1101", "2317", "2330"],
            "decision_date": [
                date(2026, 1, 2),
                date(2026, 1, 3),
                date(2026, 1, 4),
            ],
            "unrelated": [object(), object(), object()],
        }
    )

    assert list(_sample_ids(frame, (2, 0, 2))) == [
        "2330:2026-01-04",
        "1101:2026-01-02",
        "2330:2026-01-04",
    ]
