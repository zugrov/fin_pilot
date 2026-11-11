"""Непубличный CLI одной smoke-записи прогона bank↔card51.

Без ``--yes`` только расчёт. С ``--yes`` — ``reconcile_bank_card51_for_company``
при включённом флаге и finance write. Это не HTTP API.
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.clock import now
from app.config import Settings, get_settings
from app.errors import AppError
from app.models.identity import User
from app.models.provenance import ReconciliationRun
from app.security.access import access_row, find_company_across_memberships
from app.services.auth_service import normalize_email
from app.services.bank_card_reconciliation_service import (
    SampleFolder,
    build_bank_card51_report,
    reconcile_bank_card51_for_company,
)
from app.services.reconciliation_run_service import (
    QUALITY_FLAG_BANK_CARD51_DISCREPANCY,
    assert_can_persist_run,
    bank_card51_persist_status,
)

logger = logging.getLogger(__name__)

_SAFE_ERROR_CODES = frozenset({"forbidden", "email_unverified", "not_found"})


def mask_email(email: str) -> str:
    """Первый символ локальной части, без домена и остального адреса."""
    local = email.split("@", 1)[0].strip()
    if not local:
        return "***"
    return f"{local[0]}***"


def parse_period(raw: str) -> tuple[int, int]:
    parts = raw.split("-")
    if len(parts) != 2 or len(parts[0]) != 4 or len(parts[1]) != 2:
        raise AppError(422, "validation_error", "Период задаётся как ГГГГ-ММ")
    try:
        year = int(parts[0])
        month = int(parts[1])
    except ValueError as exc:
        raise AppError(422, "validation_error", "Период задаётся как ГГГГ-ММ") from exc
    if year < 2000 or year > 2100 or month < 1 or month > 12:
        raise AppError(422, "validation_error", "Период задаётся как ГГГГ-ММ")
    return year, month


def samples_from_folder(folder: Path) -> SampleFolder:
    if not folder.is_dir():
        raise AppError(503, "unavailable", "Папка образцов недоступна")

    def pick(prefix: str, suffix: str) -> Path | None:
        found: list[Path] = []
        for item in folder.iterdir():
            if not item.is_file():
                continue
            name = item.name
            if name.upper().startswith(prefix) and name.lower().endswith(suffix):
                found.append(item)
        if not found:
            return None
        return sorted(found)[0]

    bank = pick("S1_", ".txt")
    card = pick("S2_", ".xls")
    if bank is None or card is None:
        raise AppError(503, "unavailable", "В папке нет S1_*.txt и S2_*.xls")
    return SampleFolder(s1=bank, s2=card, s3=pick("S3_", ".xls"))


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return value


def preview_lines(
    report: dict,
    *,
    company_id: str,
    period: str,
    actor_mask: str,
    flag_on: bool,
) -> list[str]:
    """Только счётчики и статус. Сырой отчёт в вывод не попадает."""
    matching = report.get("matching")
    totals = report.get("control_totals")
    chain = report.get("daily_chain")
    if not isinstance(matching, dict):
        matching = {}
    if not isinstance(totals, dict):
        totals = {}
    if not isinstance(chain, dict):
        chain = {}
    aligned = bool(totals.get("aligned"))
    not_found_bank = _as_int(matching.get("not_found_bank"))
    not_found_card = _as_int(matching.get("not_found_card"))
    needs_confirmation = _as_int(matching.get("needs_confirmation_groups"))
    ambiguous = _as_int(matching.get("stage1_ambiguous"))
    chain_errors = _as_int(chain.get("errors_count"))
    status = bank_card51_persist_status(
        aligned=aligned,
        chain_error_count=chain_errors,
        not_found_bank=not_found_bank,
        not_found_card=not_found_card,
        needs_confirmation_groups=needs_confirmation,
        ambiguous_stage1=ambiguous,
    )
    lines = [
        f"company_id={company_id}",
        f"period={period}",
        f"actor={actor_mask}",
        f"status={status}",
        f"aligned={str(aligned).lower()}",
        f"matched_pair={_as_int(matching.get('matched_pair'))}",
        f"group_matched_equivalent={_as_int(matching.get('group_matched_equivalent'))}",
        f"needs_confirmation_groups={needs_confirmation}",
        f"not_found_bank={not_found_bank}",
        f"not_found_card={not_found_card}",
        f"stage1_ambiguous={ambiguous}",
        f"chain_errors={chain_errors}",
        f"flag={'on' if flag_on else 'off'}",
    ]
    if status == "completed_with_warnings":
        lines.append(f"quality_flag={QUALITY_FLAG_BANK_CARD51_DISCREPANCY}")
    return lines


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Непубличная запись одного прогона сверки bank↔card51.",
    )
    parser.add_argument("folder", type=Path, help="папка с синтетическими S1_ и S2_")
    parser.add_argument("--company-id", required=True, help="UUID организации")
    parser.add_argument("--period", required=True, help="месяц ГГГГ-ММ")
    parser.add_argument("--as-user", required=True, help="email пользователя finance write")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="записать прогон; без флага только расчёт",
    )
    return parser


def _fail(exc: AppError) -> int:
    if exc.code in _SAFE_ERROR_CODES:
        print(exc.message, file=sys.stderr)
    else:
        print("расчёт сверки не выполнен", file=sys.stderr)
    return 1


def _open_session(settings: Settings):
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return engine, factory()


def _run_ids(session, *, tenant_id: uuid.UUID, company_id: uuid.UUID) -> set[uuid.UUID]:
    # set_config в set_context локальный для транзакции: читать до commit.
    rows = session.scalars(
        select(ReconciliationRun.id).where(
            ReconciliationRun.tenant_id == tenant_id,
            ReconciliationRun.company_id == company_id,
        )
    ).all()
    return set(rows)


def main(argv: list[str] | None = None, settings: Settings | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = settings or get_settings()
    try:
        company_id = uuid.UUID(args.company_id)
    except ValueError:
        print("Некорректный company-id", file=sys.stderr)
        return 2
    try:
        year, month = parse_period(args.period)
    except AppError as exc:
        return _fail(exc)
    period = f"{year:04d}-{month:02d}"
    actor = mask_email(args.as_user)
    if args.yes and not settings.reconciliation_run_persist_enabled:
        print(
            "Запись прогона выключена: RECONCILIATION_RUN_PERSIST_ENABLED=false",
            file=sys.stderr,
        )
        return 1
    try:
        samples = samples_from_folder(args.folder)
    except AppError as exc:
        return _fail(exc)

    if not args.yes:
        try:
            report = build_bank_card51_report(samples, year=year, month=month)
        except AppError as exc:
            return _fail(exc)
        except OSError:
            logger.error(
                "reconciliation_run_cli_failed company_id=%s period=%s error=%s",
                company_id,
                period,
                "OSError",
            )
            print("расчёт сверки не выполнен", file=sys.stderr)
            return 1
        lines = preview_lines(
            report,
            company_id=str(company_id),
            period=period,
            actor_mask=actor,
            flag_on=settings.reconciliation_run_persist_enabled,
        )
        lines.append("persist=skipped")
        print("\n".join(lines))
        return 0

    engine, session = _open_session(settings)
    try:
        normalized = normalize_email(args.as_user)
        user = session.scalar(select(User).where(User.normalized_email == normalized))
        if user is None:
            print("Пользователь не найден", file=sys.stderr)
            return 1
        try:
            membership, company = find_company_across_memberships(
                session, user.id, company_id
            )
        except AppError as exc:
            if exc.status_code == 404:
                print("Нет доступа к этой организации", file=sys.stderr)
                return 1
            return _fail(exc)
        access = access_row(session, membership, company.id)
        try:
            assert_can_persist_run(membership, access, user)
        except AppError as exc:
            return _fail(exc)
        before = _run_ids(session, tenant_id=company.tenant_id, company_id=company.id)
        try:
            report = reconcile_bank_card51_for_company(
                session,
                settings,
                samples=samples,
                year=year,
                month=month,
                user=user,
                membership=membership,
                access=access,
                tenant_id=company.tenant_id,
                company_id=company.id,
                at=now(),
            )
        except AppError as exc:
            session.rollback()
            return _fail(exc)
        created = _run_ids(
            session, tenant_id=company.tenant_id, company_id=company.id
        ) - before
        if len(created) != 1:
            session.rollback()
            logger.error(
                "reconciliation_run_cli_failed company_id=%s period=%s error=%s",
                company_id,
                period,
                "persist_missing",
            )
            print("запись прогона не создана", file=sys.stderr)
            return 1
        run_id = next(iter(created))
        session.commit()
        lines = preview_lines(
            report,
            company_id=str(company_id),
            period=period,
            actor_mask=actor,
            flag_on=True,
        )
        lines.append(f"run_id={run_id}")
        lines.append("persist=written")
        logger.info(
            "reconciliation_run_cli_recorded company_id=%s run_id=%s period=%s",
            company_id,
            run_id,
            period,
        )
        print("\n".join(lines))
        return 0
    except Exception as exc:
        session.rollback()
        logger.error(
            "reconciliation_run_cli_failed company_id=%s period=%s error=%s",
            company_id,
            period,
            type(exc).__name__,
        )
        print("запись прогона не выполнена", file=sys.stderr)
        return 1
    finally:
        session.close()
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
