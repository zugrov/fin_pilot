"""Синтетический полигон: фиксированное время, seed и период проверок."""

from __future__ import annotations

from datetime import UTC, datetime

# Воспроизводимость генерации (детерминированные ID; random не используется).
POLYGON_RANDOM_SEED = 0xFA017003

# «Сейчас» для freeze(app) в интеграционных тестах полигона.
# После конца периода (Europe/Moscow), чтобы intraday_approximation не отрезала
# операции последних дней месяца в cash_total на «сейчас».
POLYGON_FROZEN_ISO = "2026-11-01T06:00:00+00:00"


def polygon_frozen_moment() -> datetime:
    moment = datetime.fromisoformat(POLYGON_FROZEN_ISO)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment


PERIOD_FROM = "2026-10-01"
PERIOD_TO = "2026-10-31"
PERIOD_QUERY = f"date_from={PERIOD_FROM}&date_to={PERIOD_TO}"

COVERAGE_THROUGH = PERIOD_TO
