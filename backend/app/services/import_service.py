import csv
import hashlib
import uuid
from collections import Counter
from datetime import datetime
from io import StringIO
from pathlib import Path

from app.config import Settings
from app.domain.imports.balances_reader import duplicate_wallet_codes, read_balances_csv
from app.domain.imports.budget_reader import read_budget_csv
from app.domain.imports.clientbank import read_clientbank, statement_period_end
from app.domain.imports.contracts import ImportFormatError, ImportLine
from app.domain.imports.csv_reader import read_csv
from app.domain.imports.dedup import classify_duplicate
from app.domain.imports.detect import detect_format
from app.domain.imports.normalize import escape_spreadsheet_text, payload_digest
from app.domain.imports.plan_reader import read_plan_csv
from app.domain.imports.revenue_reader import read_revenue_csv
from app.domain.imports.rules import RuleView, matching_category
from app.domain.imports.xlsx_reader import read_xlsx
from app.errors import AppError
from app.models.cash import CashCategory, CashTransaction, Wallet
from app.models.identity import AuditLog, Company, IdempotencyRecord, Membership, User
from app.models.imports import (
    ClassificationRule,
    EmailIngestion,
    ImportBatch,
    ImportProfile,
    IngestionDeliveryPart,
    RawImportRow,
    SourceConnection,
    SourceIdentity,
)
from app.security.access import BILLING_MANAGER, OPERATOR
from app.security.context import set_context
from app.security.tokens import canonical_hash
from app.services.balances_import import (
    batch_preview_public,
    commit_balances_batch,
    finalize_balances_batch,
    prepare_balances,
    refresh_balances_rows,
    row_preview_public,
)
from app.services.budget_import import (
    create_imported as create_budget_row,
)
from app.services.budget_import import (
    prepare_budget,
)
from app.services.budget_import import (
    revise_imported as revise_budget_row,
)
from app.services.cash_service import _audit, _remember_revision
from app.services.ingestion_delivery_service import (
    PART_PREVIEW,
    TransportContext,
    attach_delivery_id,
    content_digest,
    get_or_create_part,
    link_part_to_batch,
    refresh_delivery_transport_status,
    resolve_delivery,
    ui_delivery_key,
    ui_request_fingerprint,
)
from app.services.plan_import import (
    create_imported as create_plan_row,
)
from app.services.plan_import import (
    prepare_plan,
)
from app.services.plan_import import (
    revise_imported as revise_plan_row,
)
from app.services.revenue_import import (
    create_imported,
    link_imported,
    prepare_revenue,
    revise_imported,
)
from app.services.wallet_service import open_company
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

SCOPE = "import-upload"
TYPES = {
    "file": {"csv", "xlsx"},
    "clientbank": {"clientbank"},
    "onec": {"csv", "xlsx"},
    "email": {"clientbank"},
}
CONDITION_KEYS = {
    "description_contains",
    "counterparty_inn",
    "direction",
    "amount_min",
    "amount_max",
}


def _require_balances_import_enabled(settings: Settings, dataset: str) -> None:
    if dataset == "balances" and not settings.balances_import_enabled:
        raise AppError(
            503,
            "balances_import_disabled",
            "Импорт остатков временно недоступен",
        )


def create_source(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    *,
    name: str,
    source_type: str,
    namespace: str,
    file_format: str,
    encoding: str,
    authoritative: bool,
    wallet_id: uuid.UUID | None,
    at: datetime,
    dataset: str = "cash",
    vat_basis: str = "net",
    mailbox: dict | None = None,
) -> dict:
    _deny(membership)
    open_company(session, user, company.id, settings, "write")
    allowed = TYPES.get(source_type)
    known_encoding = encoding in {"utf-8", "utf-8-sig", "cp1251"}
    if allowed is None or file_format not in allowed or not known_encoding:
        raise AppError(422, "validation_error", "Неизвестный тип источника")
    known = {"cash", "revenue", "plan", "budget", "balances"}
    if dataset not in known or vat_basis not in {"net", "unknown"}:
        raise AppError(422, "validation_error", "Неизвестный набор данных")
    if dataset == "revenue" and (source_type != "file" or file_format != "csv"):
        raise AppError(422, "validation_error", "Продажи загружаются только из CSV")
    if dataset == "plan" and (source_type != "file" or file_format != "csv"):
        raise AppError(422, "validation_error", "План загружается только из CSV")
    if dataset == "budget" and (source_type != "file" or file_format != "csv"):
        raise AppError(422, "validation_error", "Бюджет загружается только из CSV")
    if dataset == "balances" and (source_type != "file" or file_format != "csv"):
        raise AppError(422, "validation_error", "Остатки загружаются только из CSV")
    _require_balances_import_enabled(settings, dataset)
    if source_type == "email" and dataset != "cash":
        raise AppError(422, "validation_error", "Почта принимает только денежную выписку")
    if file_format == "clientbank" and wallet_id is None:
        raise AppError(422, "validation_error", "ClientBank привязывается к кошельку")
    config: dict = {}
    secret = None
    if source_type == "email":
        from app.security.mailbox_crypto import seal_mailbox

        if mailbox is None:
            raise AppError(422, "validation_error", "Нужны настройки ящика")
        config, secret = seal_mailbox(settings, mailbox)
    if wallet_id is not None:
        wallet = _wallet(session, company, wallet_id)
        if file_format == "clientbank" and not wallet.code:
            raise AppError(422, "validation_error", "У кошелька нет кода")
    connection = SourceConnection(
        tenant_id=company.tenant_id,
        company_id=company.id,
        type=source_type,
        name=name.strip(),
        namespace=namespace.strip(),
        authoritative=authoritative,
        wallet_id=wallet_id,
        format=file_format,
        encoding=encoding,
        dataset=dataset,
        vat_basis=vat_basis,
        enabled=True,
        status="active",
        poll_interval_minutes=30,
        config_redacted=config,
        encrypted_credentials=secret,
        created_at=at,
    )
    session.add(connection)
    session.flush()
    session.add(
        ImportProfile(
            tenant_id=company.tenant_id,
            connection_id=connection.id,
            format=file_format,
            encoding=encoding,
            column_mapping={},
            date_format="DD.MM.YYYY" if file_format == "clientbank" else "YYYY-MM-DD",
            decimal_separator=".",
            sign_policy="direction",
            schema_version=1,
        )
    )
    _batch_audit(session, user, company.tenant_id, "source_created", connection.id, at)
    session.flush()
    return _source_payload(connection)


def list_sources(session: Session, company: Company) -> list[dict]:
    rows = session.scalars(
        select(SourceConnection)
        .where(
            SourceConnection.tenant_id == company.tenant_id,
            SourceConnection.company_id == company.id,
        )
        .order_by(SourceConnection.created_at)
    ).all()
    return [_source_payload(item) for item in rows]


def upload_file(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    *,
    connection_id: uuid.UUID,
    content: bytes,
    idempotency_key: str,
    at: datetime,
) -> dict:
    _deny(membership)
    open_company(session, user, company.id, settings, "write")
    if len(content) > settings.import_max_bytes:
        raise AppError(413, "payload_too_large", "Файл больше лимита")
    connection = _connection(session, company, connection_id)
    digest = content_digest(content)
    fingerprint = canonical_hash(f"{connection.id}:{digest}")
    remembered = _idempotent(session, user, idempotency_key, fingerprint)
    if remembered is not None:
        return remembered.response_body

    try:
        with session.begin_nested():
            delivery = resolve_delivery(
                session,
                company,
                connection,
                channel="ui",
                delivery_key=ui_delivery_key(user.id, idempotency_key),
                request_fingerprint=ui_request_fingerprint(connection.id, digest),
                at=at,
            )
            part = get_or_create_part(
                session,
                delivery,
                part_index=1,
                content_hash=digest,
                at=at,
            )
            if part.part_status == PART_PREVIEW and part.batch_id is not None:
                batch = session.get(ImportBatch, part.batch_id)
                if batch is not None:
                    payload = attach_delivery_id(_payload(session, batch), delivery.id)
                    refresh_delivery_transport_status(session, delivery.id, at)
                    return payload
            transport = TransportContext(delivery_id=delivery.id, part_id=part.id)
            payload = receive_import(
                session,
                membership,
                company,
                user,
                settings,
                connection_id=connection_id,
                content=content,
                idempotency_key=idempotency_key,
                at=at,
                transport=transport,
                skip_http_idempotency=True,
            )
            refresh_delivery_transport_status(session, delivery.id, at)
    except AppError:
        raise
    _remember(session, user, company.tenant_id, idempotency_key, fingerprint, payload, at)
    return payload


def receive_import(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    *,
    connection_id: uuid.UUID,
    content: bytes,
    idempotency_key: str,
    at: datetime,
    transport: TransportContext | None = None,
    skip_http_idempotency: bool = False,
) -> dict:
    _deny(membership)
    open_company(session, user, company.id, settings, "write")
    if len(content) > settings.import_max_bytes:
        raise AppError(413, "payload_too_large", "Файл больше лимита")
    connection = _connection(session, company, connection_id)
    _require_balances_import_enabled(settings, connection.dataset)
    digest = hashlib.sha256(content).hexdigest()
    fingerprint = canonical_hash(f"{connection.id}:{digest}")
    if not skip_http_idempotency:
        remembered = _idempotent(session, user, idempotency_key, fingerprint)
        if remembered is not None:
            return remembered.response_body
    existing = session.scalar(
        select(ImportBatch).where(
            ImportBatch.tenant_id == company.tenant_id,
            ImportBatch.company_id == company.id,
            ImportBatch.connection_id == connection.id,
            ImportBatch.file_hash == digest,
        )
    )
    if existing is not None:
        payload = _payload(session, existing)
        payload = _finalize_transport_and_remember(
            session,
            transport,
            existing,
            user,
            company.tenant_id,
            idempotency_key,
            fingerprint,
            payload,
            at,
            remember=not skip_http_idempotency,
        )
        return payload
    wallet_code = _bound_code(session, company, connection)
    try:
        if connection.dataset == "revenue":
            lines = _parse_revenue(content, connection, settings)
        elif connection.dataset == "plan":
            lines = _parse_plan(content, connection, settings)
        elif connection.dataset == "budget":
            lines = _parse_budget(content, connection, settings)
        elif connection.dataset == "balances":
            lines = _parse_balances(content, connection, settings)
        else:
            lines = _parse(content, connection, wallet_code, settings)
    except ImportFormatError as exc:
        raise AppError(422, exc.code, exc.message) from exc
    key = _store(settings, company.tenant_id, digest, content)
    rules = _rule_views(session, company)
    batch = ImportBatch(
        tenant_id=company.tenant_id,
        company_id=company.id,
        connection_id=connection.id,
        delivery_id=transport.delivery_id if transport is not None else None,
        file_hash=digest,
        file_storage_key=key,
        format=connection.format,
        status="validating",
        rows_total=len(lines),
        rows_valid=0,
        rows_invalid=0,
        rows_committed=0,
        quality_flags=[],
        created_at=at,
    )
    session.add(batch)
    try:
        with session.begin_nested():
            session.flush()
    except IntegrityError as exc:
        found = session.scalar(
            select(ImportBatch).where(
                ImportBatch.tenant_id == company.tenant_id,
                ImportBatch.company_id == company.id,
                ImportBatch.connection_id == connection.id,
                ImportBatch.file_hash == digest,
            )
        )
        if found is None:
            raise AppError(409, "conflict", "Файл уже импортируется") from exc
        payload = _payload(session, found)
        return _finalize_transport_and_remember(
            session,
            transport,
            found,
            user,
            company.tenant_id,
            idempotency_key,
            fingerprint,
            payload,
            at,
            remember=not skip_http_idempotency,
        )
    file_dupes: set[str] = set()
    if connection.dataset == "balances":
        file_dupes = duplicate_wallet_codes(lines)
    invalid = 0
    created_rows: list[RawImportRow] = []
    for line in lines:
        if connection.dataset == "revenue":
            prepared = prepare_revenue(session, company, connection, line)
        elif connection.dataset == "plan":
            prepared = prepare_plan(session, company, connection, line)
        elif connection.dataset == "budget":
            prepared = prepare_budget(session, company, connection, line)
        elif connection.dataset == "balances":
            prepared = prepare_balances(
                session, company, line, file_duplicate_codes=file_dupes
            )
        else:
            prepared = _prepare(session, company, connection, line, rules)
        if prepared["duplicate_status"] == "invalid":
            invalid += 1
        row = RawImportRow(
            tenant_id=company.tenant_id,
            batch_id=batch.id,
            row_number=line.row_number,
            raw_payload=line.raw,
            normalized_payload=prepared["normalized"],
            validation_errors=prepared["errors"],
            duplicate_status=prepared["duplicate_status"],
            proposed_action=prepared["proposed_action"],
            payload_hash=prepared["payload_hash"],
            external_id=getattr(line, "external_id", None) or None,
        )
        session.add(row)
        created_rows.append(row)
    if connection.dataset == "balances":
        session.flush()
        finalize_balances_batch(
            session, batch, created_rows, at=at, increment_revision=False
        )
        invalid = batch.rows_invalid
    else:
        batch.rows_invalid = invalid
        batch.rows_valid = batch.rows_total - invalid
    batch.status = "preview_ready"
    session.flush()
    payload = _payload(session, batch)
    payload = _finalize_transport_and_remember(
        session,
        transport,
        batch,
        user,
        company.tenant_id,
        idempotency_key,
        fingerprint,
        payload,
        at,
        remember=not skip_http_idempotency,
    )
    _batch_audit(session, user, company.tenant_id, "import_received", batch.id, at)
    return payload


def preview_import(
    session: Session,
    membership: Membership,
    user: User,
    settings: Settings,
    batch_id: uuid.UUID,
) -> dict:
    batch = _locked_batch(session, membership, user, settings, batch_id, "read")
    return _payload(session, batch)


def refresh_import_preview(
    session: Session,
    membership: Membership,
    user: User,
    settings: Settings,
    batch_id: uuid.UUID,
    at: datetime,
) -> dict:
    batch = _locked_batch(session, membership, user, settings, batch_id, "write", lock=True)
    if batch.status == "completed":
        raise AppError(409, "conflict", "Пакет уже проведён")
    if batch.status != "preview_ready":
        raise AppError(409, "conflict", "Preview нельзя обновить")
    company = session.get(Company, batch.company_id)
    if company is None:
        raise AppError(404, "not_found", "Фирма не найдена")
    connection = _connection(session, company, batch.connection_id)
    if connection.dataset != "balances":
        raise AppError(409, "conflict", "Обновление preview только для остатков")
    _require_balances_import_enabled(settings, connection.dataset)
    rows = _rows(session, batch)
    refresh_balances_rows(session, company, rows, at=at)
    finalize_balances_batch(session, batch, rows, at=at, increment_revision=True)
    session.flush()
    return _payload(session, batch)


def errors_csv(
    session: Session,
    membership: Membership,
    user: User,
    settings: Settings,
    batch_id: uuid.UUID,
) -> str:
    batch = _locked_batch(session, membership, user, settings, batch_id, "read")
    buffer = StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["row_number", "external_id", "errors"])
    for row in _rows(session, batch):
        if row.duplicate_status != "invalid":
            continue
        writer.writerow(
            [
                row.row_number,
                escape_spreadsheet_text(row.external_id or ""),
                escape_spreadsheet_text(";".join(row.validation_errors)),
            ]
        )
    return buffer.getvalue()


def commit_import(
    session: Session,
    membership: Membership,
    company_user: User,
    settings: Settings,
    batch_id: uuid.UUID,
    at: datetime,
    *,
    preview_token: str | None = None,
) -> dict:
    try:
        batch = _locked_batch(
            session, membership, company_user, settings, batch_id, "write", lock=True, nowait=True
        )
    except OperationalError as exc:
        if getattr(getattr(exc, "orig", None), "sqlstate", None) == "55P03":
            raise AppError(409, "conflict", "Импорт уже проводится") from exc
        raise
    company = session.get(Company, batch.company_id)
    if company is None:
        raise AppError(404, "not_found", "Фирма не найдена")
    connection = _connection(session, company, batch.connection_id)
    if connection.dataset == "balances":
        _require_balances_import_enabled(settings, connection.dataset)
        result = commit_balances_batch(
            session,
            membership,
            company,
            company_user,
            batch,
            preview_token=preview_token or "",
            at=at,
            payload_builder=_payload,
        )
        _batch_audit(session, company_user, company.tenant_id, "import_committed", batch.id, at)
        return result
    if batch.status in {"completed", "completed_with_errors"}:
        return _payload(session, batch)
    if batch.status != "preview_ready":
        raise AppError(409, "conflict", "Импорт нельзя провести")
    batch.status = "committing"
    committed = 0
    pending = False
    for row in _rows(session, batch):
        if row.proposed_action in {"skip", "review"} or row.duplicate_status in {
            "invalid",
            "ambiguous",
            "repeated",
        }:
            if row.duplicate_status in {"invalid", "ambiguous"}:
                pending = True
            continue
        if connection.dataset == "revenue":
            if row.proposed_action == "create":
                create_imported(session, company, connection, company_user, row, batch.id, at)
            elif row.proposed_action == "revise":
                revise_imported(session, company, connection, company_user, row, at)
            elif row.proposed_action == "link":
                link_imported(session, company, connection, row, at)
            else:
                continue
            committed += 1
            continue
        if connection.dataset == "plan":
            if row.proposed_action == "create":
                create_plan_row(session, company, connection, company_user, row, batch.id, at)
            elif row.proposed_action == "revise":
                revise_plan_row(session, company, connection, company_user, row, at)
            else:
                continue
            committed += 1
            continue
        if connection.dataset == "budget":
            if row.proposed_action == "create":
                create_budget_row(session, company, connection, company_user, row, batch.id, at)
            elif row.proposed_action == "revise":
                revise_budget_row(session, company, connection, company_user, row, at)
            else:
                continue
            committed += 1
            continue
        if row.proposed_action == "create":
            _create_row(session, company, connection, company_user, row, at)
            committed += 1
        elif row.proposed_action == "revise":
            _revise_row(session, company, connection, company_user, row, at)
            committed += 1
        elif row.proposed_action == "link":
            _link_row(session, company, connection, company_user, row, at)
            committed += 1
    batch.rows_committed = committed
    batch.completed_at = at
    _apply_statement_coverage(session, settings, connection, batch, at)
    if pending:
        batch.status = "completed_with_errors"
        batch.quality_flags = ["partial_import"]
    else:
        batch.status = "completed"
        batch.quality_flags = []
    session.flush()
    _batch_audit(session, company_user, company.tenant_id, "import_committed", batch.id, at)
    return _payload(session, batch)


def create_rule(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    *,
    name: str,
    priority: int,
    conditions: dict,
    category_code: str,
    at: datetime,
) -> dict:
    _deny(membership)
    open_company(session, user, company.id, settings, "write")
    if not set(conditions).issubset(CONDITION_KEYS):
        raise AppError(422, "validation_error", "Неизвестное условие правила")
    category = _category_by_code(session, company, category_code)
    if category is None:
        raise AppError(422, "validation_error", "Неизвестная категория")
    rule = ClassificationRule(
        tenant_id=company.tenant_id,
        company_id=company.id,
        name=name.strip(),
        priority=priority,
        conditions_json=conditions,
        actions_json={"category_code": category.code},
        enabled=True,
        version=1,
        created_at=at,
    )
    session.add(rule)
    session.flush()
    return _rule_payload(rule)


def list_rules(session: Session, company: Company) -> list[dict]:
    rows = session.scalars(
        select(ClassificationRule)
        .where(
            ClassificationRule.tenant_id == company.tenant_id,
            (ClassificationRule.company_id == company.id)
            | (ClassificationRule.company_id.is_(None)),
        )
        .order_by(ClassificationRule.priority)
    ).all()
    return [_rule_payload(item) for item in rows]


def preview_rule(
    session: Session,
    membership: Membership,
    user: User,
    settings: Settings,
    company: Company,
    rule_id: uuid.UUID,
) -> dict:
    _deny(membership)
    open_company(session, user, company.id, settings, "read")
    rule = session.get(ClassificationRule, rule_id)
    if rule is None or rule.tenant_id != company.tenant_id:
        raise AppError(404, "not_found", "Правило не найдено")
    if rule.company_id is not None and rule.company_id != company.id:
        raise AppError(404, "not_found", "Правило не найдено")
    view = _as_view(rule)
    rows = session.scalars(
        select(CashTransaction)
        .where(
            CashTransaction.tenant_id == company.tenant_id,
            CashTransaction.company_id == company.id,
            CashTransaction.status == "posted",
        )
        .limit(200)
    ).all()
    matches = []
    skipped = 0
    for tx in rows:
        found = matching_category(
            (view,),
            description=tx.description,
            counterparty_inn=tx.counterparty_inn or "",
            direction=tx.direction,
            amount=tx.amount,
        )
        if found is None:
            continue
        if tx.locked_classification:
            skipped += 1
            continue
        matches.append(
            {
                "transaction_id": str(tx.id),
                "description": tx.description,
                "category_code": found,
            }
        )
    return {"matches": matches, "skipped_locked": skipped}


def _prepare(session, company, connection, line: ImportLine, rules: tuple[RuleView, ...]) -> dict:
    errors = list(line.errors)
    wallet = None
    if line.wallet_code and "missing_wallet" not in errors:
        wallet = session.scalar(
            select(Wallet).where(
                Wallet.tenant_id == company.tenant_id,
                Wallet.company_id == company.id,
                Wallet.code == line.wallet_code,
            )
        )
        if wallet is None:
            errors.append("unknown_wallet")
    category_id = None
    if line.category_code:
        category = _category_by_code(session, company, line.category_code)
        if category is None:
            errors.append("unknown_category")
        else:
            category_id = str(category.id)
    rule_category = None
    if not errors and category_id is None and line.amount is not None:
        code = matching_category(
            rules,
            description=line.description,
            counterparty_inn=line.counterparty_inn,
            direction=line.direction,
            amount=line.amount,
        )
        if code:
            category = _category_by_code(session, company, code)
            if category is not None:
                rule_category = str(category.id)
    digest = "" if errors or line.amount is None else payload_digest(line)
    identity = None
    if line.external_id and not errors:
        identity = session.scalar(
            select(SourceIdentity).where(
                SourceIdentity.tenant_id == company.tenant_id,
                SourceIdentity.company_id == company.id,
                SourceIdentity.namespace == connection.namespace,
                SourceIdentity.external_id == line.external_id,
            )
        )
    others: tuple[str, ...] = ()
    if identity is None and not errors and wallet is not None and line.amount is not None:
        others = _other_ids(session, company, connection.namespace, line, wallet.id)
    status, action = classify_duplicate(
        has_errors=bool(errors),
        identity_hash=None if identity is None else identity.payload_hash,
        payload_hash=digest,
        other_ids=others,
        authoritative=connection.authoritative,
    )
    match_id = others[0] if status == "linked" and others else None
    if identity is not None and status == "changed":
        match_id = str(identity.canonical_entity_id)
    return {
        "errors": errors,
        "duplicate_status": status,
        "proposed_action": action,
        "payload_hash": digest or None,
        "normalized": {
            "values": line.canonical(),
            "wallet_id": None if wallet is None else str(wallet.id),
            "category_id": category_id,
            "rule_category_id": rule_category,
            "match_id": match_id,
        },
    }


def _other_ids(session, company, namespace: str, line: ImportLine, wallet_id) -> tuple[str, ...]:
    rows = session.scalars(
        select(SourceIdentity.canonical_entity_id)
        .join(CashTransaction, CashTransaction.id == SourceIdentity.canonical_entity_id)
        .where(
            SourceIdentity.tenant_id == company.tenant_id,
            SourceIdentity.company_id == company.id,
            SourceIdentity.namespace != namespace,
            CashTransaction.status == "posted",
            CashTransaction.wallet_id == wallet_id,
            CashTransaction.business_date == line.business_date,
            CashTransaction.amount == line.amount,
            CashTransaction.direction == line.direction,
            CashTransaction.currency == line.currency,
            CashTransaction.description == line.description,
        )
    ).all()
    return tuple(str(item) for item in rows if item is not None)


def _create_row(session, company, connection, user, row: RawImportRow, at: datetime) -> None:
    data = row.normalized_payload or {}
    values = data["values"]
    category_id = data.get("category_id") or data.get("rule_category_id")
    tx = CashTransaction(
        tenant_id=company.tenant_id,
        company_id=company.id,
        wallet_id=uuid.UUID(data["wallet_id"]),
        business_date=_date(values["business_date"]),
        occurred_at=None,
        direction=values["direction"],
        amount=_decimal(values["amount"]),
        currency="RUB",
        category_id=None if category_id is None else uuid.UUID(category_id),
        description=values["description"],
        document_number=values["document_number"] or None,
        counterparty_inn=values["counterparty_inn"] or None,
        counterparty_name=values["counterparty_name"] or None,
        source="import",
        status="posted",
        classification_origin="rule" if data.get("rule_category_id") else "none",
        locked_classification=False,
        created_by=user.id,
        version=1,
        created_at=at,
        updated_at=at,
    )
    session.add(tx)
    session.flush()
    _identity(session, company, connection, row, tx.id, at)
    _audit(session, user, company.tenant_id, "transaction_imported", tx.id, at)


def _revise_row(session, company, connection, user, row: RawImportRow, at: datetime) -> None:
    data = row.normalized_payload or {}
    tx = session.get(CashTransaction, uuid.UUID(data["match_id"]))
    if tx is None or tx.tenant_id != company.tenant_id:
        raise AppError(404, "not_found", "Операция источника не найдена")
    values = data["values"]
    _remember_revision(session, tx, user, at)
    tx.amount = _decimal(values["amount"])
    tx.business_date = _date(values["business_date"])
    tx.description = values["description"]
    tx.document_number = values["document_number"] or None
    tx.counterparty_inn = values["counterparty_inn"] or None
    tx.counterparty_name = values["counterparty_name"] or None
    if not tx.locked_classification:
        category_id = data.get("category_id") or data.get("rule_category_id")
        if category_id:
            tx.category_id = uuid.UUID(category_id)
            if data.get("rule_category_id") and not data.get("category_id"):
                tx.classification_origin = "rule"
    tx.version += 1
    tx.updated_at = at
    identity = _find_identity(session, company, connection.namespace, row.external_id or "")
    if identity is not None and row.payload_hash:
        identity.payload_hash = row.payload_hash
    session.flush()


def _link_row(session, company, connection, user, row: RawImportRow, at: datetime) -> None:
    data = row.normalized_payload or {}
    tx = session.get(CashTransaction, uuid.UUID(data["match_id"]))
    if tx is None or tx.tenant_id != company.tenant_id:
        raise AppError(404, "not_found", "Операция источника не найдена")
    _identity(session, company, connection, row, tx.id, at)
    if tx.locked_classification or tx.category_id is not None:
        return
    category_id = data.get("rule_category_id")
    if not category_id:
        return
    _remember_revision(session, tx, user, at)
    tx.category_id = uuid.UUID(category_id)
    tx.classification_origin = "rule"
    tx.version += 1
    tx.updated_at = at
    session.flush()
    _ = user


def _identity(session, company, connection, row: RawImportRow, tx_id, at: datetime) -> None:
    session.add(
        SourceIdentity(
            tenant_id=company.tenant_id,
            company_id=company.id,
            connection_id=connection.id,
            namespace=connection.namespace,
            entity_type="cash_transaction",
            external_id=row.external_id or "",
            canonical_entity_id=tx_id,
            payload_hash=row.payload_hash or "",
            created_at=at,
        )
    )
    session.flush()


def _parse_balances(content: bytes, connection: SourceConnection, settings: Settings):
    if connection.format != "csv":
        raise ImportFormatError("unsupported_format", "Остатки загружаются только из CSV")
    return read_balances_csv(
        content,
        encoding=connection.encoding,
        max_rows=settings.import_max_rows,
    )


def _parse_budget(content: bytes, connection: SourceConnection, settings: Settings):
    return read_budget_csv(content, encoding=connection.encoding, max_rows=settings.import_max_rows)


def _parse_plan(content: bytes, connection: SourceConnection, settings: Settings):
    detect_format(content, connection.format, connection.encoding)
    if connection.format != "csv":
        raise ImportFormatError("unsupported_format", "План загружается только из CSV")
    return read_plan_csv(content, encoding=connection.encoding, max_rows=settings.import_max_rows)


def _parse_revenue(content: bytes, connection: SourceConnection, settings: Settings):
    detect_format(content, connection.format, connection.encoding)
    if connection.format != "csv":
        raise ImportFormatError("unsupported_format", "Продажи загружаются только из CSV")
    return read_revenue_csv(
        content,
        encoding=connection.encoding,
        max_rows=settings.import_max_rows,
        vat_basis=connection.vat_basis,
    )


def _parse(content: bytes, connection: SourceConnection, wallet_code: str, settings: Settings):
    detect_format(content, connection.format, connection.encoding)
    if connection.format == "csv":
        return read_csv(content, encoding=connection.encoding, max_rows=settings.import_max_rows)
    if connection.format == "xlsx":
        return read_xlsx(
            content,
            max_rows=settings.import_max_rows,
            max_uncompressed=settings.import_max_uncompressed_bytes,
        )
    return read_clientbank(
        content,
        encoding=connection.encoding,
        max_rows=settings.import_max_rows,
        wallet_code=wallet_code,
    )


def _payload(session: Session, batch: ImportBatch) -> dict:
    rows = _rows(session, batch)
    counts: Counter[str] = Counter(item.duplicate_status for item in rows)
    connection = session.get(SourceConnection, batch.connection_id)
    balances = connection is not None and connection.dataset == "balances"
    payload = {
        "id": str(batch.id),
        "status": batch.status,
        "connection_id": str(batch.connection_id),
        "file_hash": batch.file_hash,
        "rows_committed": batch.rows_committed,
        "quality_flags": list(batch.quality_flags or []),
        "counts": {
            "new": counts["new"],
            "repeated": counts["repeated"],
            "changed": counts["changed"],
            "invalid": counts["invalid"],
            "ambiguous": counts["ambiguous"],
            "linked": counts["linked"],
        },
        "rows": [
            row_preview_public(item) if balances else _row_preview_default(item)
            for item in rows
        ],
    }
    if balances:
        payload.update(batch_preview_public(batch, rows))
    return payload


def _row_preview_default(item: RawImportRow) -> dict:
    return {
        "row_number": item.row_number,
        "external_id": item.external_id,
        "duplicate_status": item.duplicate_status,
        "proposed_action": item.proposed_action,
        "errors": list(item.validation_errors or []),
    }


def _rows(session: Session, batch: ImportBatch) -> list[RawImportRow]:
    return list(
        session.scalars(
            select(RawImportRow)
            .where(RawImportRow.batch_id == batch.id, RawImportRow.tenant_id == batch.tenant_id)
            .order_by(RawImportRow.row_number)
        ).all()
    )


def _locked_batch(
    session,
    membership,
    user,
    settings,
    batch_id,
    mode: str,
    *,
    lock: bool = False,
    nowait: bool = False,
):
    set_context(session, tenant_id=membership.tenant_id, user_id=user.id)
    query = select(ImportBatch).where(ImportBatch.id == batch_id)
    if lock:
        query = query.with_for_update(nowait=nowait)
    batch = session.scalar(query)
    if batch is None or batch.tenant_id != membership.tenant_id:
        raise AppError(404, "not_found", "Импорт не найден")
    _deny(membership)
    open_company(session, user, batch.company_id, settings, mode)
    return batch


def _connection(session, company, connection_id) -> SourceConnection:
    connection = session.get(SourceConnection, connection_id)
    if connection is None or connection.tenant_id != company.tenant_id:
        raise AppError(404, "not_found", "Источник не найден")
    if connection.company_id != company.id or not connection.enabled:
        raise AppError(404, "not_found", "Источник не найден")
    return connection


def _wallet(session, company, wallet_id) -> Wallet:
    wallet = session.get(Wallet, wallet_id)
    if wallet is None or wallet.tenant_id != company.tenant_id or wallet.company_id != company.id:
        raise AppError(404, "not_found", "Кошелёк не найден")
    return wallet


def _bound_code(session, company, connection: SourceConnection) -> str:
    if connection.format != "clientbank":
        return ""
    if connection.wallet_id is None:
        raise AppError(422, "validation_error", "ClientBank привязывается к кошельку")
    wallet = _wallet(session, company, connection.wallet_id)
    if not wallet.code:
        raise AppError(422, "validation_error", "У кошелька нет кода")
    return wallet.code


def _category_by_code(session, company, code: str) -> CashCategory | None:
    return session.scalar(
        select(CashCategory).where(
            CashCategory.tenant_id == company.tenant_id,
            CashCategory.code == code,
        )
    )


def _rule_views(session, company) -> tuple[RuleView, ...]:
    rows = session.scalars(
        select(ClassificationRule).where(
            ClassificationRule.tenant_id == company.tenant_id,
            ClassificationRule.enabled.is_(True),
            (ClassificationRule.company_id == company.id)
            | (ClassificationRule.company_id.is_(None)),
        )
    ).all()
    return tuple(_as_view(item) for item in rows)


def _as_view(rule: ClassificationRule) -> RuleView:
    return RuleView(
        rule.priority,
        rule.enabled,
        dict(rule.conditions_json),
        str(rule.actions_json.get("category_code") or ""),
    )


def _find_identity(session, company, namespace: str, external_id: str) -> SourceIdentity | None:
    return session.scalar(
        select(SourceIdentity).where(
            SourceIdentity.tenant_id == company.tenant_id,
            SourceIdentity.company_id == company.id,
            SourceIdentity.namespace == namespace,
            SourceIdentity.external_id == external_id,
        )
    )


def _store(settings: Settings, tenant_id, digest: str, content: bytes) -> str:
    root = Path(settings.import_storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    relative = Path(str(tenant_id)) / digest
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise AppError(400, "validation_error", "Некорректный путь")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return relative.as_posix()


def _deny(membership: Membership) -> None:
    if membership.role in {OPERATOR, BILLING_MANAGER}:
        raise AppError(403, "forbidden", "Импорт недоступен")


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _apply_statement_coverage(session, settings, connection: SourceConnection, batch, at) -> None:
    if connection.format != "clientbank":
        return
    path = Path(settings.import_storage_dir) / batch.file_storage_key
    if not path.is_file():
        return
    try:
        end = statement_period_end(path.read_bytes(), encoding=connection.encoding)
    except ImportFormatError:
        return
    if end is not None and (
        connection.coverage_through is None or end > connection.coverage_through
    ):
        connection.coverage_through = end
    found = session.scalar(
        select(EmailIngestion).where(
            EmailIngestion.tenant_id == batch.tenant_id,
            EmailIngestion.batch_id == batch.id,
        )
    )
    if found is None:
        return
    found.status = "committed"
    connection.last_success_at = at


def _source_payload(connection: SourceConnection) -> dict:
    return {
        "id": str(connection.id),
        "name": connection.name,
        "type": connection.type,
        "namespace": connection.namespace,
        "format": connection.format,
        "encoding": connection.encoding,
        "dataset": connection.dataset,
        "vat_basis": connection.vat_basis,
        "coverage_through": (
            None if connection.coverage_through is None else connection.coverage_through.isoformat()
        ),
        "authoritative": connection.authoritative,
        "wallet_id": None if connection.wallet_id is None else str(connection.wallet_id),
        "poll_interval_minutes": connection.poll_interval_minutes,
        "last_attempt_at": _iso(connection.last_attempt_at),
        "last_success_at": _iso(connection.last_success_at),
        "next_attempt_at": _iso(connection.next_attempt_at),
        "last_error": connection.last_error,
        "host": (connection.config_redacted or {}).get("host"),
        "folder": (connection.config_redacted or {}).get("folder"),
        "sender": (connection.config_redacted or {}).get("sender"),
        "username": (connection.config_redacted or {}).get("username"),
    }


def _rule_payload(rule: ClassificationRule) -> dict:
    return {
        "id": str(rule.id),
        "name": rule.name,
        "priority": rule.priority,
        "conditions": rule.conditions_json,
        "actions": rule.actions_json,
        "enabled": rule.enabled,
        "version": rule.version,
    }


def _finalize_transport_and_remember(
    session: Session,
    transport: TransportContext | None,
    batch: ImportBatch,
    user: User,
    tenant_id: uuid.UUID,
    idempotency_key: str,
    fingerprint: str,
    payload: dict,
    at: datetime,
    *,
    remember: bool,
) -> dict:
    if transport is not None:
        part = session.get(IngestionDeliveryPart, transport.part_id)
        if part is not None:
            link_part_to_batch(
                session,
                part,
                batch,
                part_status=PART_PREVIEW,
                error_code=None,
                at=at,
            )
        payload = attach_delivery_id(payload, transport.delivery_id)
    if remember:
        _remember(session, user, tenant_id, idempotency_key, fingerprint, payload, at)
    return payload


def _idempotent(session, user, key: str, request_hash: str) -> IdempotencyRecord | None:
    row = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.user_id == user.id,
            IdempotencyRecord.scope == SCOPE,
            IdempotencyRecord.idempotency_key == key,
        )
    )
    if row is None:
        return None
    if row.request_hash != request_hash:
        raise AppError(409, "idempotency_conflict", "Другой файл для того же ключа")
    return row


def _remember(session, user, tenant_id, key, request_hash, payload, at) -> None:
    try:
        with session.begin_nested():
            session.add(
                IdempotencyRecord(
                    tenant_id=tenant_id,
                    user_id=user.id,
                    scope=SCOPE,
                    idempotency_key=key,
                    request_hash=request_hash,
                    status_code=200,
                    response_body=payload,
                    created_at=at,
                )
            )
            session.flush()
    except IntegrityError as exc:
        row = _idempotent(session, user, key, request_hash)
        if row is None:
            raise AppError(409, "conflict", "Ключ idempotency уже занят") from exc


def _batch_audit(session, user, tenant_id, action: str, entity_id, at: datetime) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user.id,
            action=action,
            entity_type="import_batch",
            entity_id=entity_id,
            before_redacted=None,
            after_redacted=None,
            request_id=None,
            created_at=at,
        )
    )


def _date(raw: str):
    from datetime import date

    return date.fromisoformat(raw)


def _decimal(raw: str):
    from decimal import Decimal

    return Decimal(raw)
