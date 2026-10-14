from datetime import UTC, datetime
from decimal import Decimal

from app.domain.cash.balance import Anchor, CashLine, WalletInput
from app.domain.cash.summary import summarize


def _line(
    direction: str,
    amount: str,
    *,
    section: str | None = None,
    transfer: str | None = None,
    status: str = "posted",
    at: datetime | None = None,
) -> CashLine:
    return CashLine(
        direction=direction,
        amount=Decimal(amount),
        status=status,
        business_date=datetime(2026, 10, 20, tzinfo=UTC).date(),
        occurred_at=at or datetime(2026, 10, 20, 12, tzinfo=UTC),
        transfer_kind=transfer,
        category_section=section,
    )


def _wallet(
    amount: str,
    lines: tuple[CashLine, ...] = (),
    *,
    availability: str = "spendable",
    available_from: datetime | None = None,
    reserve: str = "0",
    anchor: bool = True,
) -> WalletInput:
    opening = None
    if anchor:
        opening = Anchor(datetime(2026, 10, 1, tzinfo=UTC), Decimal(amount))
    return WalletInput(opening, availability, available_from, Decimal(reserve), lines)


def test_a1_posted_movements_change_balance() -> None:
    wallet = _wallet(
        "100000",
        (_line("in", "50000"), _line("out", "20000"), _line("in", "999", status="void")),
    )
    view = summarize((wallet,), datetime(2026, 10, 21, tzinfo=UTC), Decimal("0"))
    assert view.cash_total == Decimal("130000.00")


def test_draft_and_pre_anchor_do_not_count() -> None:
    early = datetime(2026, 9, 1, tzinfo=UTC)
    wallet = _wallet(
        "100000",
        (_line("in", "50000", status="draft"), _line("out", "20000", at=early)),
    )
    view = summarize((wallet,), datetime(2026, 10, 21, tzinfo=UTC), Decimal("0"))
    assert view.cash_total == Decimal("100000.00")


def test_a2_internal_transfer_is_not_external() -> None:
    left = _wallet("100000", (_line("out", "30000", transfer="internal"),))
    right = _wallet("0", (_line("in", "30000", transfer="internal"),))
    view = summarize((left, right), datetime(2026, 10, 21, tzinfo=UTC), Decimal("0"))
    assert view.cash_total == Decimal("100000.00")
    assert view.external_in == Decimal("0.00")
    assert view.external_out == Decimal("0.00")


def test_a3_owner_contribution_is_financing_not_revenue() -> None:
    wallet = _wallet("0", (_line("in", "100000", section="financing"),))
    view = summarize((wallet,), datetime(2026, 10, 21, tzinfo=UTC), Decimal("0"))
    assert view.cash_total == Decimal("100000.00")
    assert view.financing_in == Decimal("100000.00")
    assert view.revenue is None
    assert "missing_revenue_source" in view.quality_flags


def test_a4_advance_does_not_create_revenue() -> None:
    wallet = _wallet("0", (_line("in", "60000"),))
    view = summarize((wallet,), datetime(2026, 10, 21, tzinfo=UTC), Decimal("0"))
    assert view.cash_total == Decimal("60000.00")
    assert view.revenue is None


def test_a5_cash_is_not_reported_as_revenue() -> None:
    wallet = _wallet("0", (_line("in", "60000"),))
    view = summarize((wallet,), datetime(2026, 10, 21, tzinfo=UTC), Decimal("0"))
    assert view.cash_total == Decimal("60000.00")
    assert view.revenue is None


def test_a6_missing_sales_source_is_unavailable() -> None:
    view = summarize((_wallet("0"),), datetime(2026, 10, 21, tzinfo=UTC), Decimal("0"))
    assert view.revenue is None
    assert view.revenue != 0


def test_a7_restricted_and_reserve() -> None:
    spendable = _wallet("200000")
    deposit = _wallet("100000", availability="restricted")
    view = summarize(
        (spendable, deposit),
        datetime(2026, 10, 21, tzinfo=UTC),
        Decimal("50000"),
    )
    assert view.cash_total == Decimal("300000.00")
    assert view.available == Decimal("200000.00")
    assert view.restricted == Decimal("100000.00")
    assert view.headroom == Decimal("150000.00")


def test_a8_missing_anchor_is_unavailable() -> None:
    moment = datetime(2026, 10, 21, tzinfo=UTC)
    view = summarize((_wallet("0", anchor=False),), moment, Decimal("0"))
    assert view.cash_total is None
    assert "missing_anchor" in view.quality_flags
