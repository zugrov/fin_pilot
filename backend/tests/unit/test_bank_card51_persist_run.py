"""Запись прогона сверки bank↔card51: флаг, статус, вызов после расчёта."""

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from app.config import Settings
from app.domain.imports.fa_r03.bank_card51_matching import (
    BankCardMatchReport,
    BankMovement,
    CardMovementAggregate,
    match_bank_to_card51,
)
from app.errors import AppError
from app.services.bank_card_reconciliation_service import (
    group_refs_from_match,
    reconcile_bank_card51_for_company,
)
from app.services.reconciliation_run_service import (
    QUALITY_FLAG_BANK_CARD51_DISCREPANCY,
    _bank_card51_metrics,
    bank_card51_persist_status,
    record_bank_card51_run,
)


def test_persist_flag_follows_env(monkeypatch) -> None:
    monkeypatch.setenv("RECONCILIATION_RUN_PERSIST_ENABLED", "false")
    assert Settings().reconciliation_run_persist_enabled is False
    monkeypatch.setenv("RECONCILIATION_RUN_PERSIST_ENABLED", "true")
    assert Settings().reconciliation_run_persist_enabled is True


def test_flag_off_does_not_touch_session() -> None:
    session = MagicMock()
    result = record_bank_card51_run(
        session,
        Settings(reconciliation_run_persist_enabled=False),
        tenant_id=uuid4(),
        company_id=uuid4(),
        user=SimpleNamespace(id=uuid4(), email_verified_at=None),
        membership=SimpleNamespace(role="viewer"),
        access=None,
        period_year=2026,
        period_month=8,
        aligned=True,
        chain_error_count=0,
        matching={},
        group_refs=[],
        control_totals={},
        input_fingerprints=[],
        input_hashes={},
        at=datetime.now(UTC),
    )
    assert result is None
    session.add.assert_not_called()
    session.begin_nested.assert_not_called()
    session.execute.assert_not_called()


def test_clean_reconciliation_status_is_passed() -> None:
    status = bank_card51_persist_status(
        aligned=True,
        chain_error_count=0,
        not_found_bank=0,
        not_found_card=0,
        needs_confirmation_groups=0,
        ambiguous_stage1=0,
    )
    metrics = _bank_card51_metrics(
        status=status,
        chain_error_count=0,
        matching={"matched_pair": 2},
        control_totals={"aligned": True},
    )
    assert status == "passed"
    assert metrics["matched_pair"] == 2
    assert "quality_flag" not in metrics
    assert "payment_id" not in metrics


def test_discrepancy_is_quality_flag_not_block() -> None:
    status = bank_card51_persist_status(
        aligned=False,
        chain_error_count=1,
        not_found_bank=2,
        not_found_card=0,
        needs_confirmation_groups=1,
        ambiguous_stage1=0,
    )
    metrics = _bank_card51_metrics(
        status=status,
        chain_error_count=1,
        matching={"not_found_bank": 2},
        control_totals={"aligned": False},
    )
    assert status == "completed_with_warnings"
    assert metrics["quality_flag"] == QUALITY_FLAG_BANK_CARD51_DISCREPANCY


def test_status_outside_success_does_not_insert(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.reconciliation_run_service.bank_card51_persist_status",
        lambda **_kwargs: "failed",
    )
    session = MagicMock()
    result = record_bank_card51_run(
        session,
        Settings(reconciliation_run_persist_enabled=True),
        tenant_id=uuid4(),
        company_id=uuid4(),
        user=SimpleNamespace(id=uuid4(), email_verified_at=datetime.now(UTC)),
        membership=SimpleNamespace(role="owner"),
        access=None,
        period_year=2026,
        period_month=8,
        aligned=True,
        chain_error_count=0,
        matching={},
        group_refs=[],
        control_totals={},
        input_fingerprints=[],
        input_hashes={},
        at=datetime.now(UTC),
    )
    assert result is None
    session.begin_nested.assert_not_called()


def test_group_refs_have_no_document_text_or_payment_link() -> None:
    day = date(2026, 8, 3)
    bank = BankMovement(
        index=0,
        direction="in",
        business_date=day,
        amount=Decimal("10.00"),
        document_number="",
    )
    card = CardMovementAggregate(
        index=0,
        direction="in",
        business_date=day,
        amount=Decimal("10.00"),
        document_title="pii-document-title",
        counter_accounts=("62.01",),
        source_row_count=1,
    )
    refs = group_refs_from_match(match_bank_to_card51([bank], [card]))
    assert len(refs) == 1
    assert refs[0]["kind"] == "matched_pair"
    assert set(refs[0]) == {
        "business_date",
        "direction",
        "amount",
        "kind",
        "bank_documents",
        "card_aggregates",
    }
    assert "pii-document-title" not in str(refs)


def _call_reconcile() -> dict:
    return reconcile_bank_card51_for_company(
        MagicMock(),
        Settings(reconciliation_run_persist_enabled=True),
        samples=MagicMock(),
        year=2026,
        month=8,
        user=MagicMock(),
        membership=MagicMock(),
        access=None,
        tenant_id=uuid4(),
        company_id=uuid4(),
        at=datetime.now(UTC),
    )


def test_calculation_error_does_not_record(monkeypatch) -> None:
    def _boom(*_args, **_kwargs):
        raise AppError(422, "invalid_format", "карточка 51")

    called = {"n": 0}

    def _record(*_args, **_kwargs):
        called["n"] += 1

    monkeypatch.setattr(
        "app.services.bank_card_reconciliation_service._bank_card51_calculation",
        _boom,
    )
    monkeypatch.setattr(
        "app.services.bank_card_reconciliation_service.record_bank_card51_run",
        _record,
    )
    with pytest.raises(AppError) as exc:
        _call_reconcile()
    assert exc.value.code == "invalid_format"
    assert called["n"] == 0


def test_reconcile_records_only_after_calculation(monkeypatch) -> None:
    order: list[str] = []
    report = {
        "control_totals": {"aligned": True},
        "daily_chain": {"errors_count": 0},
        "matching": {},
    }

    def _calc(*_args, **_kwargs):
        order.append("calc")
        return report, BankCardMatchReport(bank_count=0, card_aggregate_count=0)

    def _record(*_args, **_kwargs):
        order.append("record")
        return None

    monkeypatch.setattr(
        "app.services.bank_card_reconciliation_service._bank_card51_calculation",
        _calc,
    )
    monkeypatch.setattr(
        "app.services.bank_card_reconciliation_service.record_bank_card51_run",
        _record,
    )
    monkeypatch.setattr(
        "app.services.bank_card_reconciliation_service._sample_fingerprints",
        lambda _samples: [],
    )
    monkeypatch.setattr(
        "app.services.bank_card_reconciliation_service._input_hashes",
        lambda _fingerprints, *, year, month: {},
    )
    assert _call_reconcile() is report
    assert order == ["calc", "record"]
