"""Exchange-session window calculation for forward labels."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from src.core.horizon import (
    PRODUCTION_HORIZON,
    require_production_horizon,
    require_supported_horizon,
)

from .contracts import LabelWindow


class TradingCalendar:
    """Immutable ordered exchange-session calendar."""

    def __init__(self, sessions: Sequence[date]) -> None:
        normalized = tuple(sessions)
        if not normalized:
            raise ValueError("trading calendar cannot be empty")
        if tuple(sorted(set(normalized))) != normalized:
            raise ValueError("trading sessions must be unique and strictly increasing")
        self._sessions: tuple[date, ...] = normalized
        self._positions: dict[date, int] = {
            session: position for position, session in enumerate(normalized)
        }

    @property
    def sessions(self) -> tuple[date, ...]:
        return self._sessions

    def is_session(self, session_date: date) -> bool:
        return session_date in self._positions

    def label_window(
        self,
        decision_date: date,
        *,
        horizon: int = PRODUCTION_HORIZON,
        research: bool = False,
    ) -> LabelWindow:
        horizon = (
            require_supported_horizon(horizon)
            if research
            else require_production_horizon(horizon)
        )
        try:
            decision_position = self._positions[decision_date]
        except KeyError as exc:
            raise ValueError("decision_date must be an exchange session") from exc
        entry_position = decision_position + 1
        exit_position = decision_position + horizon
        if exit_position >= len(self._sessions):
            raise ValueError("calendar does not contain the complete label window")
        return LabelWindow(
            decision_date=decision_date,
            entry_date=self._sessions[entry_position],
            exit_date=self._sessions[exit_position],
            horizon=horizon,
        )


__all__ = ["TradingCalendar"]
