import uuid
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.domain.imports.balances_reader import BalancesLine
from app.errors import AppError
from app.models.cash import OpeningBalance, Wallet
from app.models.identity import Company, Membership, User
from app.models.imports import ImportBatch, RawImportRow
from app.services import wallet_service
from sqlalchemy import select
from sqlalchemy.orm import Session

BATCH_PREVIEW_KEY = "_batch_preview"
INTENTS = {"create", "replace", "unchanged"}


def opening_moment(company: Company, as_of: date) -> datetime:
    tz = ZoneInfo(company.timezone)
    return datetime(as_of.year, as_of.month, as_of.day, 0, 0, 0, tzinfo=tz)


def opening_snapshot(opening: OpeningBalance | None) -> dict | None:
    if opening is None:
        return None
    return {
        "opening_id": str(opening.id),
        "amount": f"{opening.amount:.2f}",
        "effective_at": opening.effective_at.isoformat(),
    }


def wallet_context(wallet: Wallet, company: Company) -> dict:
    return {
        "wallet_id": str(wallet.id),
        "wallet_code": wallet.code or "",
        "currency": wallet.currency,
        "company_timezone": company.timezone,
    }


def contexts_match(stored: dict | None, wallet: Wallet, company: Company) -> bool:
    if stored is None:
        return False
    ctx = wallet_context(wallet, company)
    return (
        stored.get("wallet_id") == ctx["wallet_id"]
        and stored.get("wallet_code") == ctx["wallet_code"]
        and stored.get("currency") == ctx["currency"]
        and stored.get("company_timezone") == ctx["company_timezone"]
    )


def openings_equal(left: dict | None, right: dict | None) -> bool:
    if left is None and right is None:
        return True
    if left is None or right is None:
        return False
    return (
        left.get("opening_id") == right.get("opening_id")
        and left.get("amount") == right.get("amount")
        and left.get("effective_at") == right.get("effective_at")
    )


def after_snapshot(amount: Decimal, effective_at: datetime) -> dict:
    return {"amount": f"{amount:.2f}", "effective_at": effective_at.isoformat()}


def batch_preview_row(rows: list[RawImportRow]) -> RawImportRow | None:
    if not rows:
        return None
    return min(rows, key=lambda item: item.row_number)


def read_batch_preview(normalized: dict | None) -> dict:
    if not normalized:
        return {}
    block = normalized.get(BATCH_PREVIEW_KEY)
    return block if isinstance(block, dict) else {}


def write_batch_preview(normalized: dict | None, preview: dict) -> dict:
    base = dict(normalized or {})
    base[BATCH_PREVIEW_KEY] = preview
    return base


def prepare_balances(
    session: Session,
    company: Company,
    line: BalancesLine,
    *,
    file_duplicate_codes: set[str],
) -> dict:
    errors = list(line.errors)
    if line.wallet_code and line.wallet_code in file_duplicate_codes:
        errors.append("duplicate_wallet_code_in_file")
    wallet = None
    if line.wallet_code and "missing_wallet_code" not in errors:
        wallet = session.scalar(
            select(Wallet).where(
                Wallet.tenant_id == company.tenant_id,
                Wallet.company_id == company.id,
                Wallet.code == line.wallet_code,
            )
        )
        if wallet is None:
            errors.append("unknown_wallet")
        elif line.currency and wallet.currency != line.currency:
            errors.append("currency_mismatch")
    intent = "create"
    before = None
    after = None
    effective_at = None
    amount = line.balance
    stale_guard = None
    wallet_id = None
    if not errors and wallet is not None and line.as_of is not None and amount is not None:
        wallet_id = str(wallet.id)
        effective_at = opening_moment(company, line.as_of)
        after = after_snapshot(amount, effective_at)
        active = session.scalar(
            select(OpeningBalance).where(
                OpeningBalance.wallet_id == wallet.id,
                OpeningBalance.status == "active",
            )
        )
        before = opening_snapshot(active)
        stale_guard = {
            "opening": before,
            "wallet_context": wallet_context(wallet, company),
        }
        if active is None:
            intent = "create"
        elif active.amount == amount and active.effective_at == effective_at:
            intent = "unchanged"
        else:
            intent = "replace"
    status = "invalid" if errors else "new"
    action = "skip" if errors else "create"
    normalized: dict = {
        "values": line.canonical(),
        "wallet_id": wallet_id,
        "effective_at": None if effective_at is None else effective_at.isoformat(),
        "intent": intent if not errors else "invalid",
        "before": before,
        "after": after,
        "stale_guard": stale_guard,
    }
    return {
        "errors": errors,
        "duplicate_status": status,
        "proposed_action": action,
        "payload_hash": None,
        "normalized": normalized,
    }


def finalize_balances_batch(
    session: Session,
    batch: ImportBatch,
    rows: list[RawImportRow],
    *,
    at: datetime,
    increment_revision: bool,
) -> None:
    dupes = duplicate_wallet_codes_from_rows(rows)
    anchor = batch_preview_row(rows)
    if anchor is None:
        return
    prior = read_batch_preview(anchor.normalized_payload)
    revision = int(prior.get("revision") or 0)
    if increment_revision or not prior.get("token"):
        revision += 1
    token = str(uuid.uuid4())
    blocked = bool(dupes)
    preview_meta = {
        "token": token,
        "revision": revision,
        "prepared_at": at.isoformat(),
        "duplicate_wallet_codes": sorted(dupes),
        "commit_blocked": blocked,
        "completed_response": None if increment_revision else prior.get("completed_response"),
    }
    if blocked:
        flags = list(batch.quality_flags or [])
        flags.append("duplicate_wallet_in_file")
        batch.quality_flags = list(set(flags))
        for row in rows:
            code = (row.raw_payload or {}).get("wallet_code", "").strip()
            if code in dupes:
                errors = list(row.validation_errors or [])
                if "duplicate_wallet_code_in_file" not in errors:
                    errors.append("duplicate_wallet_code_in_file")
                row.validation_errors = errors
                row.duplicate_status = "invalid"
                row.proposed_action = "skip"
                if isinstance(row.normalized_payload, dict):
                    row.normalized_payload["intent"] = "invalid"
    anchor.normalized_payload = write_batch_preview(anchor.normalized_payload, preview_meta)
    batch.rows_invalid = sum(1 for row in rows if row.duplicate_status == "invalid")
    batch.rows_valid = batch.rows_total - batch.rows_invalid


def duplicate_wallet_codes_from_rows(rows: list[RawImportRow]) -> set[str]:
    seen: set[str] = set()
    dupes: set[str] = set()
    for row in rows:
        code = (row.raw_payload or {}).get("wallet_code", "").strip()
        if not code:
            continue
        if code in seen:
            dupes.add(code)
        seen.add(code)
    return dupes


def refresh_balances_rows(
    session: Session,
    company: Company,
    rows: list[RawImportRow],
    *,
    at: datetime,
) -> None:
    dupes = duplicate_wallet_codes_from_rows(rows)
    for row in rows:
        line = BalancesLine(
            row_number=row.row_number,
            wallet_code=(row.raw_payload or {}).get("wallet_code", "").strip(),
            as_of=_date_from_raw(row.raw_payload or {}),
            balance=_amount_from_raw(row.raw_payload or {}),
            currency=(row.raw_payload or {}).get("currency", "").strip().upper(),
            errors=(),
            raw=dict(row.raw_payload or {}),
        )
        prepared = prepare_balances(session, company, line, file_duplicate_codes=dupes)
        row.normalized_payload = prepared["normalized"]
        row.validation_errors = prepared["errors"]
        row.duplicate_status = prepared["duplicate_status"]
        row.proposed_action = prepared["proposed_action"]


def _date_from_raw(raw: dict) -> date | None:
    value = raw.get("as_of", "").strip()
    if not value:
        return None
    try:
        parts = value.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))
    except (ValueError, IndexError, TypeError):
        return None


def _amount_from_raw(raw: dict) -> Decimal | None:
    from decimal import InvalidOperation

    from app.domain.money import money

    value = raw.get("balance", "").strip()
    if not value:
        return None
    try:
        amount = Decimal(value)
        return money(amount)
    except InvalidOperation:
        return None


def validate_stale_before_write(
    session: Session,
    company: Company,
    row: RawImportRow,
    wallet: Wallet,
) -> None:
    data = row.normalized_payload or {}
    guard = data.get("stale_guard") or {}
    if not contexts_match(guard.get("wallet_context"), wallet, company):
        raise AppError(409, "stale_preview", "Контекст счёта изменился — обновите preview")
    active = session.scalar(
        select(OpeningBalance).where(
            OpeningBalance.wallet_id == wallet.id,
            OpeningBalance.status == "active",
        )
    )
    current = opening_snapshot(active)
    if not openings_equal(guard.get("opening"), current):
        raise AppError(409, "stale_preview", "Начальный остаток изменился — обновите preview")


def commit_balances_batch(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    batch: ImportBatch,
    *,
    preview_token: str,
    at: datetime,
    payload_builder,
) -> dict:
    rows = list(
        session.scalars(
            select(RawImportRow)
            .where(RawImportRow.batch_id == batch.id, RawImportRow.tenant_id == batch.tenant_id)
            .order_by(RawImportRow.row_number)
        ).all()
    )
    anchor = batch_preview_row(rows)
    if anchor is None:
        raise AppError(422, "validation_error", "Пустой пакет")
    meta = read_batch_preview(anchor.normalized_payload)
    if batch.status == "completed":
        stored = meta.get("completed_response")
        if isinstance(stored, dict):
            return stored
        return payload_builder(session, batch)
    if batch.status != "preview_ready":
        raise AppError(409, "conflict", "Импорт нельзя провести")
    if meta.get("commit_blocked"):
        raise AppError(409, "conflict", "Пакет заблокирован: повтор wallet_code в файле")
    if not preview_token or preview_token != meta.get("token"):
        raise AppError(409, "preview_token_invalid", "Нужен актуальный Preview-Token")
    if any(row.duplicate_status == "invalid" for row in rows):
        raise AppError(409, "conflict", "В пакете есть ошибки строк")
    apply_rows = [row for row in rows if row.proposed_action == "create"]
    wallet_ids: list[uuid.UUID] = []
    for row in apply_rows:
        wid = (row.normalized_payload or {}).get("wallet_id")
        if wid:
            wallet_ids.append(uuid.UUID(str(wid)))
    wallet_ids = sorted(set(wallet_ids))
    wallets = wallet_service.lock_wallets_for_opening(session, company.tenant_id, wallet_ids)
    for row in apply_rows:
        wid = uuid.UUID(str((row.normalized_payload or {})["wallet_id"]))
        validate_stale_before_write(session, company, row, wallets[wid])
    batch.status = "committing"
    committed = 0
    results: list[dict] = []
    for row in apply_rows:
        data = row.normalized_payload or {}
        intent = data.get("intent")
        if intent not in INTENTS:
            raise AppError(422, "validation_error", "Некорректная строка пакета")
        if intent == "unchanged":
            results.append(
                {
                    "row_number": row.row_number,
                    "intent": intent,
                    "opening_id": (data.get("before") or {}).get("opening_id"),
                }
            )
            continue
        wid = uuid.UUID(str(data["wallet_id"]))
        wallet = wallets[wid]
        validate_stale_before_write(session, company, row, wallet)
        amount = Decimal(str(data["after"]["amount"]))
        effective_at = datetime.fromisoformat(str(data["after"]["effective_at"]))
        opening = wallet_service.set_opening_balance(
            session,
            membership,
            wallet,
            user,
            effective_at=effective_at,
            amount=amount,
        )
        committed += 1
        results.append(
            {
                "row_number": row.row_number,
                "intent": intent,
                "opening_id": str(opening.id),
            }
        )
        data["committed_opening_id"] = str(opening.id)
        row.normalized_payload = data
    batch.rows_committed = committed
    batch.completed_at = at
    batch.status = "completed"
    batch.quality_flags = []
    response = payload_builder(session, batch)
    meta = read_batch_preview(anchor.normalized_payload)
    meta["completed_response"] = response
    meta["commit_results"] = results
    anchor.normalized_payload = write_batch_preview(anchor.normalized_payload, meta)
    session.flush()
    return response


def row_preview_public(row: RawImportRow) -> dict:
    data = row.normalized_payload or {}
    return {
        "row_number": row.row_number,
        "external_id": row.external_id,
        "duplicate_status": row.duplicate_status,
        "proposed_action": row.proposed_action,
        "errors": list(row.validation_errors or []),
        "intent": data.get("intent"),
        "before": data.get("before"),
        "after": data.get("after"),
    }


def batch_preview_public(batch: ImportBatch, rows: list[RawImportRow]) -> dict:
    anchor = batch_preview_row(rows)
    meta = read_batch_preview(anchor.normalized_payload if anchor else None)
    return {
        "preview_token": meta.get("token"),
        "preview_revision": meta.get("revision"),
        "commit_blocked": bool(meta.get("commit_blocked")),
    }
