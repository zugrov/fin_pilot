"""Ручной ORACLE сигналов для профиля gap_digest (FA-R09.P2).

Расчёт на freeze 2026-11-01T06:00:00+00:00, report_date 2026-10-31, Europe/Moscow.
Не использует alert_service / telegram_digest — только входные данные профиля и
арифметика денежного прогноза (opening + posted net + план out на дату).

Профиль: opening 5000, out 350000 (2026-10-12), план out 90000 (2026-11-05).
Posted cash на 2026-10-31: 5000 - 350000 = -345000 (closing).
План 90000 на 2026-11-05 усугубляет дефицит → первая дата gap 2026-10-12 (уже отрицательно)
или первая «новая» gap по прогнозу — сверено с API forecast при фиксации пакета.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.domain.telegram_text import signal_type_label

# Контрагент в cash.csv / new_counterparty evidence (ключ counterparty).
PRIVACY_COUNTERPARTY_LABEL = "Privacy Oracle CP"


@dataclass(frozen=True)
class CashGapOracle:
    signal_type: str
    gap_date: str
    gap_amount: str
    label_ru: str


@dataclass(frozen=True)
class CounterpartySignalOracle:
    signal_type: str
    counterparty_evidence: str
    label_ru: str


# Ручной расчёт: opening 5000 − out 350000 = −345000 на 2026-10-31;
# gap_amount = |min(closing,0)| + max(0, outflows_plan) на gap_date = 435000 (план 2026-11-05).
CASH_GAP = CashGapOracle(
    signal_type="cash_gap",
    gap_date="2026-10-31",
    gap_amount="435000.00",
    label_ru=signal_type_label("cash_gap"),
)

NEW_COUNTERPARTY = CounterpartySignalOracle(
    signal_type="new_counterparty",
    counterparty_evidence=PRIVACY_COUNTERPARTY_LABEL,
    label_ru=signal_type_label("new_counterparty"),
)

LARGE_OUTGOING = CounterpartySignalOracle(
    signal_type="large_outgoing",
    counterparty_evidence="",
    label_ru=signal_type_label("large_outgoing"),
)


def expected_digest_signal_types() -> frozenset[str]:
    return frozenset(
        {
            CASH_GAP.signal_type,
            NEW_COUNTERPARTY.signal_type,
            LARGE_OUTGOING.signal_type,
        }
    )


def gap_worsened_amount() -> str:
    """Сумма для ухудшения дефицита (>20% materiality) после первого дайджеста."""
    base = Decimal(CASH_GAP.gap_amount)
    worsened = (base * Decimal("1.25")).quantize(Decimal("0.01"))
    return format(worsened, "f")
