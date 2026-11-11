"""Сверка S1 ↔ карточка 51 (FA-R03.2).

Просмотр отчёта не пишет в БД. Запись прогона — отдельный вызов после расчёта,
флаг `reconciliation_run_persist_enabled` по умолчанию выключен.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.config import Settings
from app.domain.imports.clientbank import read_clientbank
from app.domain.imports.fa_r03.bank_card51_matching import (
    BankCardMatchReport,
    BankMovement,
    aggregate_card_rows,
    match_bank_to_card51,
)
from app.domain.imports.fa_r03.clientbank_daily import parse_clientbank_daily_sections
from app.domain.imports.fa_r03.reconcile import (
    Account51Totals,
    account51_totals_equal,
    daily_chain_errors,
    totals_from_daily_sections,
)
from app.domain.imports.fa_r03.xls_reader import XlsFormatError, read_card51, read_osv
from app.domain.money import money, money_str
from app.errors import AppError
from app.models.identity import Membership, User
from app.security.access import CompanyAccess
from app.services.reconciliation_run_service import record_bank_card51_run
from sqlalchemy.orm import Session

ZERO = Decimal("0.00")

_FINGERPRINT_PROFILES = {
    "s1": "ru-bank-clientbank/1.0.0",
    "s2": "1c-card51-xls/1",
    "s3": "1c-osv-xls/1",
}


@dataclass(frozen=True)
class SampleFolder:
    s1: Path
    s2: Path
    s3: Path | None


def _resolved_samples_base(root: str) -> Path | None:
    """Корень образцов: только абсолютный путь из env, без выхода за base."""
    raw = root.strip()
    if not raw or "\0" in raw:
        return None
    base = Path(raw).expanduser().resolve(strict=False)
    if not base.is_dir():
        return None
    return base


def _path_inside_base(path: Path, base: Path) -> bool:
    try:
        path.resolve().relative_to(base.resolve())
    except ValueError:
        return False
    return True


def resolve_local_sample_folder(root: str, year: int, month: int) -> SampleFolder | None:
    """Локальные образцы вне git; каталоги фиксированы относительно base."""
    base = _resolved_samples_base(root)
    if base is None:
        return None
    if year == 2026 and month == 9:
        folder_name = "fa-r03-client-samples"
    elif year == 2026 and month == 8:
        folder_name = "fa-r03-client-samples-2026-08"
    else:
        return None
    folder = (base / folder_name).resolve(strict=False)
    if not _path_inside_base(folder, base) or not folder.is_dir():
        return None

    def pick(prefix: str, suffix: str) -> Path | None:
        for item in sorted(folder.iterdir()):
            if not item.is_file():
                continue
            if not _path_inside_base(item, base):
                continue
            name = item.name.upper()
            if name.startswith(prefix) and name.lower().endswith(suffix):
                return item
        return None

    s1 = pick("S1_", ".txt")
    s2 = pick("S2_", ".xls")
    if s1 is None or s2 is None:
        return None
    s3 = pick("S3_", ".xls")
    return SampleFolder(s1=s1, s2=s2, s3=s3)


def _detect_encoding(raw: bytes) -> str:
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        return "cp1251"


def _load_bank_movements(
    s1_path: Path,
    *,
    year: int,
    month: int,
) -> tuple[list[BankMovement], bytes, str]:
    raw = s1_path.read_bytes()
    encoding = _detect_encoding(raw)
    lines = read_clientbank(raw, encoding=encoding, max_rows=100_000, wallet_code="51")
    docs: list[BankMovement] = []
    index = 0
    for line in lines:
        if line.errors or line.business_date is None or line.amount is None:
            continue
        if line.business_date.year != year or line.business_date.month != month:
            continue
        docs.append(
            BankMovement(
                index=index,
                direction=line.direction,
                business_date=line.business_date,
                amount=money(line.amount),
                document_number=str(line.document_number or "").strip(),
            )
        )
        index += 1
    return docs, raw, encoding


def _totals_payload(label: str, item: Account51Totals) -> dict[str, str]:
    return {
        "source": label,
        "opening": money_str(item.opening),
        "total_in": money_str(item.total_in),
        "total_out": money_str(item.total_out),
        "closing": money_str(item.closing),
    }


def build_bank_card51_report(samples: SampleFolder, *, year: int, month: int) -> dict[str, Any]:
    report, _match = _bank_card51_calculation(samples, year=year, month=month)
    return report


def _bank_card51_calculation(
    samples: SampleFolder, *, year: int, month: int
) -> tuple[dict[str, Any], BankCardMatchReport]:
    bank_docs, raw_s1, encoding = _load_bank_movements(samples.s1, year=year, month=month)
    try:
        card_sheet = read_card51(samples.s2)
    except XlsFormatError as exc:
        raise AppError(422, "invalid_format", f"карточка 51: {exc}") from exc

    card_rows = [
        row
        for row in card_sheet.rows
        if row.business_date.year == year and row.business_date.month == month
    ]
    card_aggs = aggregate_card_rows(card_rows)
    match_report = match_bank_to_card51(bank_docs, card_aggs)

    total_in = money(sum((doc.amount for doc in bank_docs if doc.direction == "in"), ZERO))
    total_out = money(sum((doc.amount for doc in bank_docs if doc.direction == "out"), ZERO))
    sections = parse_clientbank_daily_sections(raw_s1, encoding=encoding)
    chain_errors = daily_chain_errors(sections)
    daily = totals_from_daily_sections(sections)
    s1_totals = Account51Totals(
        opening=daily.opening,
        total_in=total_in,
        total_out=total_out,
        closing=daily.closing,
    )
    s2_totals = Account51Totals(
        opening=card_sheet.opening_balance or ZERO,
        total_in=card_sheet.turnover_debit or ZERO,
        total_out=card_sheet.turnover_credit or ZERO,
        closing=card_sheet.closing_balance or ZERO,
    )
    s3_totals: Account51Totals | None = None
    if samples.s3 is not None and samples.s3.is_file():
        try:
            osv = read_osv(samples.s3)
            row = osv.by_code("51")
            if row is not None:
                s3_totals = Account51Totals(
                    opening=row.opening_debit - row.opening_credit,
                    total_in=row.turnover_debit,
                    total_out=row.turnover_credit,
                    closing=row.closing_debit - row.closing_credit,
                )
        except XlsFormatError:
            s3_totals = None

    control_sources = [("S1", s1_totals), ("S2", s2_totals)]
    if s3_totals is not None:
        control_sources.append(("S3", s3_totals))
    if s3_totals is not None:
        aligned = account51_totals_equal(s1_totals, s2_totals, s3_totals)
    else:
        aligned = account51_totals_equal(s1_totals, s2_totals)

    ambiguous_groups = [
        {
            "business_date": group.key.business_date.isoformat(),
            "direction": group.key.direction,
            "amount": money_str(group.key.amount),
            "bank_documents": len(group.bank_indices),
            "card_aggregates": len(group.card_indices),
            "kind": group.kind,
        }
        for group in match_report.groups
        if group.kind in {"group_matched_equivalent", "needs_confirmation"}
        and len(group.bank_indices) > 1
    ]

    report = {
        "period": {"year": year, "month": month},
        "quality": "ok",
        "control_totals": {
            "sources": [_totals_payload(label, totals) for label, totals in control_sources],
            "aligned": aligned,
            "tolerance": "0.00",
        },
        "daily_chain": {
            "sections": len(sections),
            "errors_count": len(chain_errors),
            "error_codes": chain_errors[:20],
        },
        "matching": {
            "bank_documents": match_report.bank_count,
            "card_aggregates": match_report.card_aggregate_count,
            "matched_pair": match_report.matched_pair_count,
            "group_matched_equivalent": match_report.group_matched_equivalent_count,
            "needs_confirmation_groups": match_report.needs_confirmation_group_count,
            "owner_confirmed_groups": 0,
            "stage1_ambiguous": match_report.ambiguous_stage1_count,
            "not_found_bank": len(match_report.not_found_bank_indices),
            "not_found_card": len(match_report.not_found_card_indices),
            "multi_document_groups": ambiguous_groups,
        },
    }
    return report, match_report


def group_refs_from_match(match_report: BankCardMatchReport) -> list[dict[str, Any]]:
    """Ссылки на группы: дата, направление, сумма, вид. Без текстов документов."""
    refs: list[dict[str, Any]] = []
    for group in match_report.groups:
        refs.append(
            {
                "business_date": group.key.business_date.isoformat(),
                "direction": group.key.direction,
                "amount": money_str(group.key.amount),
                "kind": group.kind,
                "bank_documents": len(group.bank_indices),
                "card_aggregates": len(group.card_indices),
            }
        )
    return refs


def _file_fingerprint(path: Path, role: str) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "role": role,
        "profile_code": _FINGERPRINT_PROFILES[role],
        "content_sha256": hashlib.sha256(raw).hexdigest(),
        "byte_size": len(raw),
    }


def _sample_fingerprints(samples: SampleFolder) -> list[dict[str, Any]]:
    fingerprints = [
        _file_fingerprint(samples.s1, "s1"),
        _file_fingerprint(samples.s2, "s2"),
    ]
    if samples.s3 is not None and samples.s3.is_file():
        fingerprints.append(_file_fingerprint(samples.s3, "s3"))
    return fingerprints


def _input_hashes(
    fingerprints: list[dict[str, Any]], *, year: int, month: int
) -> dict[str, str]:
    canonical = json.dumps(
        {
            "period": [year, month],
            "files": [
                {"role": item["role"], "content_sha256": item["content_sha256"]}
                for item in fingerprints
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {"canonical_sha256": digest}


def reconcile_bank_card51_for_company(
    session: Session,
    settings: Settings,
    *,
    samples: SampleFolder,
    year: int,
    month: int,
    user: User,
    membership: Membership,
    access: CompanyAccess | None,
    tenant_id: uuid.UUID,
    company_id: uuid.UUID,
    at: datetime,
) -> dict[str, Any]:
    """Расчёт сверки и, если флаг включён, append-only прогон в той же сессии.

    Ошибка расчёта не создаёт строку. Ошибка INSERT не отменяет уже собранный отчёт.
    Нет finance-write или неподтверждённый email — 403, строка не пишется.
    """
    report, match_report = _bank_card51_calculation(samples, year=year, month=month)
    fingerprints = _sample_fingerprints(samples)
    record_bank_card51_run(
        session,
        settings,
        tenant_id=tenant_id,
        company_id=company_id,
        user=user,
        membership=membership,
        access=access,
        period_year=year,
        period_month=month,
        aligned=bool(report["control_totals"]["aligned"]),
        chain_error_count=int(report["daily_chain"]["errors_count"]),
        matching=report["matching"],
        group_refs=group_refs_from_match(match_report),
        control_totals=report["control_totals"],
        input_fingerprints=fingerprints,
        input_hashes=_input_hashes(fingerprints, year=year, month=month),
        at=at,
    )
    return report


def report_for_company_local(
    *,
    samples_root: str,
    year: int,
    month: int,
) -> dict[str, Any]:
    folder = resolve_local_sample_folder(samples_root, year, month)
    if folder is None:
        raise AppError(
            503,
            "unavailable",
            "локальные образцы FA-R03 не настроены или отсутствуют для периода",
        )
    return build_bank_card51_report(folder, year=year, month=month)
