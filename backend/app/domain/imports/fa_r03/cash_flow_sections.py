"""Эталонные секции ОДДС по корреспондирующему счёту (FA-R03.2, не правила продукта)."""

from __future__ import annotations

INBOUND_SECTIONS: dict[str, str] = {
    "62.01": "operating",
    "62.02": "operating",
    "57.03": "operating",
    "90.01.1": "operating",
    "55.03": "investing",
    "91.01": "investing",
}

OUTBOUND_SECTIONS: dict[str, str] = {
    "60.01": "operating",
    "60.02": "operating",
    "70": "operating",
    "69.11": "operating",
    "68.90": "operating",
    "68.10": "operating",
    "91.02": "operating",
    "55.03": "investing",
    "50.01": "technical",
}


def section_for_account(account: str, direction: str) -> str | None:
    table = INBOUND_SECTIONS if direction == "in" else OUTBOUND_SECTIONS
    return table.get(account.strip())
