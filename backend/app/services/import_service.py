import csv
import hashlib
import time
import uuid
from collections import Counter
from datetime import datetime
from io import StringIO
from pathlib import Path

from app.config import Settings
from app.domain.imports.balances_reader import duplicate_wallet_codes, read_balances_csv
from app.domain.imports.budget_reader import read_budget_csv
from app.domain.imports.clientbank import read_clientbank
from app.domain.imports.contracts import ImportFormatError, ImportLine
from app.domain.imports.csv_reader import read_csv
from app.domain.imports.detect import detect_format
from app.domain.imports.identity_lock import lock_identity_keys
from app.domain.imports.import_meta import parse_row_meta
from app.domain.imports.normalize import escape_spreadsheet_text, payload_digest
from app.domain.imports.plan_reader import read_plan_csv
from app.domain.imports.prepare_common import classify_import_row
from app.domain.imports.revenue_reader import read_revenue_csv
from app.domain.imports.revision import commit_decision
from app.domain.imports.rules import RuleView, matching_category
from app.domain.imports.source_identity_slot import (
    apply_identity_watermark,
    entity_type_conflict,
    load_identity_slot,
)
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
from app.services.cash_service import _audit, _remember_revision, lock_transaction_for_match
from app.services.dataset_coverage_service import invalidate_reconciled_for_connection
from app.services.delivery_validation_service import (
    assert_commit_allowed,
    refresh_delivery_validation,
    resolve_commit_delivery_context,
)
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
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

SCOPE = "import-upload"
RULE_PREVIEW_MATCH_LIMIT = 200
RULE_APPLY_SCAN_LIMIT = 1000
RULE_TX_FETCH_BATCH = 500
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

    payload: dict | None = None
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
            if payload is None:
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
    file_uq_conflict = False
    try:
        with session.begin_nested():
            session.add(batch)
            session.flush()
    except IntegrityError as exc:
        if not _is_import_batch_file_uq(exc):
            raise
        file_uq_conflict = True
    if file_uq_conflict:
        found = _batch_after_file_uq_conflict(session, company, connection, digest)
        if found is None:
            raise AppError(409, "conflict", "Файл уже импортируется")
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
            prepared = prepare_balances(session, company, line, file_duplicate_codes=file_dupes)
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
            external_id=prepared.get("external_id") or getattr(line, "external_id", None) or None,
            source_revision=prepared.get("source_revision"),
            operation=str(prepared.get("operation") or "upsert"),
        )
        session.add(row)
        created_rows.append(row)
    if connection.dataset == "balances":
        session.flush()
        finalize_balances_batch(session, batch, created_rows, at=at, increment_revision=False)
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
    delivery_id: uuid.UUID | None = None,
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
    commit_delivery = resolve_commit_delivery_context(session, batch, delivery_id)
    assert_commit_allowed(session, commit_delivery, batch, connection)
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
        invalidate_reconciled_for_connection(
            session, connection, at, reason="import_commit"
        )
        if commit_delivery is not None:
            refresh_delivery_validation(session, commit_delivery, connection, at)
        return result
    if batch.status in {"completed", "completed_with_errors"}:
        payload = _payload(session, batch)
        if commit_delivery is not None:
            payload = attach_delivery_id(payload, commit_delivery.id)
        return payload
    if batch.status != "preview_ready":
        raise AppError(409, "conflict", "Импорт нельзя провести")
    batch.status = "committing"
    committed, pending, has_review = _commit_identity_batch(
        session, company, connection, company_user, batch, at
    )
    batch.rows_committed = committed
    batch.completed_at = at
    _apply_statement_coverage(session, settings, connection, batch, at)
    flags: list[str] = []
    if pending:
        flags.append("partial_import")
    if has_review:
        flags.append("rows_in_review")
    if pending or has_review:
        batch.status = "completed_with_errors"
        batch.quality_flags = flags
    else:
        batch.status = "completed"
        batch.quality_flags = []
    session.flush()
    _batch_audit(session, company_user, company.tenant_id, "import_committed", batch.id, at)
    invalidate_reconciled_for_connection(session, connection, at, reason="import_commit")
    if commit_delivery is not None:
        refresh_delivery_validation(session, commit_delivery, connection, at)
    payload = _payload(session, batch)
    if commit_delivery is not None:
        payload = attach_delivery_id(payload, commit_delivery.id)
    return payload


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
    if not _has_rule_condition(conditions):
        raise AppError(422, "validation_error", "Нужно хотя бы одно условие")
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


def update_classification_rule(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    rule_id: uuid.UUID,
    *,
    enabled: bool | None,
    priority: int | None,
    name: str | None,
    at: datetime,
) -> dict:
    _deny(membership)
    open_company(session, user, company.id, settings, "write")
    rule = _load_company_rule(session, company, rule_id)
    changed = False
    if enabled is not None and rule.enabled != enabled:
        rule.enabled = enabled
        changed = True
    if priority is not None and rule.priority != priority:
        rule.priority = priority
        changed = True
    if name is not None:
        trimmed = name.strip()
        if rule.name != trimmed:
            rule.name = trimmed
            changed = True
    if changed:
        rule.version += 1
        session.flush()
        _rule_updated_audit(session, user, company.tenant_id, rule.id, rule, at)
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
    rule = _load_company_rule(session, company, rule_id)
    view = _as_view(rule)
    all_rules = _rule_views(session, company)
    matches: list[dict] = []
    total_matches = 0
    skipped_locked = 0
    skipped_categorized = 0
    skipped_higher_priority = 0
    for batch in _posted_transaction_batches(session, company):
        for tx in batch:
            outcome = _rule_transaction_outcome(view, all_rules, tx)
            if outcome == "no_match":
                continue
            if outcome == "higher_priority":
                skipped_higher_priority += 1
                continue
            if outcome == "locked":
                skipped_locked += 1
                continue
            if outcome == "categorized":
                skipped_categorized += 1
                continue
            total_matches += 1
            if len(matches) < RULE_PREVIEW_MATCH_LIMIT:
                matches.append(_rule_match_payload(tx, view.category_code))
    return {
        "matches": matches,
        "total_matches": total_matches,
        "truncated": total_matches > RULE_PREVIEW_MATCH_LIMIT,
        "skipped_locked": skipped_locked,
        "skipped_categorized": skipped_categorized,
        "skipped_higher_priority": skipped_higher_priority,
    }


def apply_classification_rule(
    session: Session,
    membership: Membership,
    user: User,
    settings: Settings,
    company: Company,
    rule_id: uuid.UUID,
    *,
    after_business_date=None,
    after_transaction_id: uuid.UUID | None = None,
    at: datetime,
) -> dict:
    _deny(membership)
    open_company(session, user, company.id, settings, "write")
    rule = _load_company_rule(session, company, rule_id)
    if not rule.enabled:
        raise AppError(409, "conflict", "Правило отключено")
    view = _as_view(rule)
    all_rules = _rule_views(session, company)
    category = _category_by_code(session, company, view.category_code)
    if category is None:
        raise AppError(422, "validation_error", "Категория правила не найдена")
    applied = 0
    skipped_locked = 0
    skipped_categorized = 0
    skipped_higher_priority = 0
    total_matches = 0
    scanned = 0
    last_date = None
    last_id = None
    for batch in _posted_transaction_batches(
        session,
        company,
        after_date=after_business_date,
        after_id=after_transaction_id,
    ):
        for tx in batch:
            scanned += 1
            if scanned > RULE_APPLY_SCAN_LIMIT:
                break
            last_date = tx.business_date
            last_id = tx.id
            outcome = _rule_transaction_outcome(view, all_rules, tx)
            if outcome == "no_match":
                continue
            if outcome == "higher_priority":
                skipped_higher_priority += 1
                continue
            if outcome == "locked":
                skipped_locked += 1
                continue
            if outcome == "categorized":
                skipped_categorized += 1
                continue
            total_matches += 1
            row = lock_transaction_for_match(
                session,
                tenant_id=company.tenant_id,
                company_id=company.id,
                transaction_id=tx.id,
            )
            if row.status != "posted":
                continue
            locked_outcome = _rule_transaction_outcome(view, all_rules, row)
            if locked_outcome == "locked":
                skipped_locked += 1
                continue
            if locked_outcome == "categorized":
                skipped_categorized += 1
                continue
            if locked_outcome == "higher_priority":
                skipped_higher_priority += 1
                continue
            if locked_outcome != "eligible":
                continue
            _remember_revision(session, row, user, at)
            row.category_id = category.id
            row.classification_origin = "rule"
            row.version += 1
            row.updated_at = at
            session.flush()
            applied += 1
        if scanned > RULE_APPLY_SCAN_LIMIT:
            break
    has_more = False
    if last_id is not None and scanned >= RULE_APPLY_SCAN_LIMIT:
        has_more = _posted_transactions_remain(session, company, last_date, last_id)
    elif last_id is not None and scanned < RULE_APPLY_SCAN_LIMIT:
        has_more = False
    cursor = None
    if has_more and last_date is not None and last_id is not None:
        cursor = {
            "business_date": last_date.isoformat(),
            "transaction_id": str(last_id),
        }
    payload = {
        "applied": applied,
        "skipped_locked": skipped_locked,
        "skipped_categorized": skipped_categorized,
        "skipped_higher_priority": skipped_higher_priority,
        "total_matches": total_matches,
        "has_more": has_more,
        "cursor": cursor,
    }
    _rule_apply_audit(session, user, company.tenant_id, rule.id, payload, at)
    return payload


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
    meta = parse_row_meta(line.raw, external_id=line.external_id)
    digest = "" if errors or line.amount is None else payload_digest(line)
    identity = None
    if meta.external_id and not errors:
        identity = load_identity_slot(session, company, connection.namespace, meta.external_id)
    others: tuple[str, ...] = ()
    if identity is None and not errors and wallet is not None and line.amount is not None:
        others = _other_ids(session, company, connection.namespace, line, wallet.id)
    classified = classify_import_row(
        errors=errors,
        meta=meta,
        identity=identity,
        entity_type="cash_transaction",
        payload_hash=digest,
        other_ids=others,
        authoritative=connection.authoritative,
    )
    match_id = others[0] if classified["duplicate_status"] == "linked" and others else None
    if identity is not None and classified["duplicate_status"] == "changed":
        match_id = str(identity.canonical_entity_id)
    return {
        "errors": classified["errors"],
        "duplicate_status": classified["duplicate_status"],
        "proposed_action": classified["proposed_action"],
        "payload_hash": classified["payload_hash"],
        "source_revision": classified["source_revision"],
        "operation": classified["operation"],
        "external_id": classified["external_id"],
        "normalized": {
            "values": line.canonical(),
            "wallet_id": None if wallet is None else str(wallet.id),
            "category_id": category_id,
            "rule_category_id": rule_category,
            "match_id": match_id,
            "review_reason": classified["review_reason"],
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
    identity = load_identity_slot(session, company, connection.namespace, row.external_id or "")
    if identity is not None:
        apply_identity_watermark(
            identity,
            source_revision=row.source_revision,
            payload_hash=row.payload_hash,
            advance_only=False,
        )
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
            last_source_revision=row.source_revision,
            created_at=at,
        )
    )
    session.flush()


def _dataset_entity(dataset: str) -> str:
    mapping = {
        "cash": "cash_transaction",
        "revenue": "revenue_entry",
        "plan": "planned_event",
        "budget": "budget_line",
    }
    return mapping[dataset]


def _revision_error_message(code: str) -> str:
    messages = {
        "stale_revision": "Ревизия источника устарела",
        "revision_payload_conflict": "Та же ревизия с другим содержимым",
        "revision_required": "Для изменения нужна ревизия источника",
        "identity_type_conflict": "Ключ источника занят другим типом",
    }
    return messages.get(code, "Конфликт импорта")


def _ensure_commit_match_id(
    row: RawImportRow, identity: SourceIdentity | None, entity_type: str
) -> None:
    if identity is None:
        return
    data = dict(row.normalized_payload or {})
    if data.get("match_id"):
        return
    entity_id = None
    if entity_type == "cash_transaction":
        entity_id = identity.canonical_entity_id
    elif entity_type == "revenue_entry":
        entity_id = identity.revenue_entry_id
    elif entity_type == "planned_event":
        entity_id = identity.planned_event_id
    elif entity_type == "budget_line":
        entity_id = identity.budget_line_id
    if entity_id is None:
        return
    data["match_id"] = str(entity_id)
    row.normalized_payload = data


def _commit_other_ids(
    session, company, connection: SourceConnection, row: RawImportRow
) -> tuple[str, ...]:
    if connection.dataset != "cash":
        return ()
    data = row.normalized_payload or {}
    wallet_raw = data.get("wallet_id")
    values = data.get("values") or {}
    if not wallet_raw or not row.external_id:
        return ()
    try:
        wallet_id = uuid.UUID(str(wallet_raw))
    except ValueError:
        return ()
    line = ImportLine(
        row.row_number,
        row.external_id or "",
        values.get("wallet_code", ""),
        _date(values["business_date"]) if values.get("business_date") else None,
        values.get("direction", ""),
        _decimal(values["amount"]) if values.get("amount") else None,
        values.get("currency", "RUB"),
        values.get("counterparty_inn", ""),
        values.get("counterparty_name", ""),
        values.get("description", ""),
        values.get("document_number", ""),
        values.get("category_code", ""),
        values.get("direction_code", ""),
        (),
        values,
    )
    if line.amount is None or line.business_date is None or line.direction not in {"in", "out"}:
        return ()
    return _other_ids(session, company, connection.namespace, line, wallet_id)


def _commit_identity_batch(
    session,
    company,
    connection: SourceConnection,
    company_user: User,
    batch: ImportBatch,
    at: datetime,
) -> tuple[int, bool, bool]:
    rows = _rows(session, batch)
    entity_type = _dataset_entity(connection.dataset)
    keys = sorted(
        {
            (connection.namespace, row.external_id)
            for row in rows
            if row.external_id and row.operation != "unpost" and not row.validation_errors
        }
    )
    lock_identity_keys(session, company.tenant_id, company.id, list(keys))
    committed = 0
    pending = False
    has_review = False
    for row in rows:
        if row.operation == "unpost":
            has_review = True
            continue
        if row.validation_errors or row.duplicate_status == "invalid":
            pending = True
            continue
        if row.duplicate_status == "ambiguous":
            pending = True
            continue
        if not row.external_id:
            pending = True
            continue
        identity = load_identity_slot(session, company, connection.namespace, row.external_id)
        conflict = entity_type_conflict(identity, entity_type)
        if conflict:
            raise AppError(409, conflict, _revision_error_message(conflict))
        payload_hash = row.payload_hash or ""
        others = _commit_other_ids(session, company, connection, row)
        decision = commit_decision(
            has_errors=False,
            operation=row.operation,
            identity_hash=None if identity is None else identity.payload_hash,
            payload_hash=payload_hash,
            other_ids=others,
            authoritative=connection.authoritative,
            incoming_revision=row.source_revision,
            applied_revision=None if identity is None else identity.last_source_revision,
            preview_action=row.proposed_action,
            identity_exists=identity is not None,
        )
        if decision.error_code:
            raise AppError(409, decision.error_code, _revision_error_message(decision.error_code))
        action = decision.action
        if (
            identity is not None
            and row.payload_hash
            and identity.payload_hash != row.payload_hash
            and action == "create"
            and row.source_revision is None
            and identity.last_source_revision is None
        ):
            action = "revise"
        if action == "revise":
            _ensure_commit_match_id(row, identity, entity_type)
        if action == "skip":
            if identity is not None:
                apply_identity_watermark(
                    identity,
                    source_revision=row.source_revision,
                    payload_hash=row.payload_hash,
                    advance_only=decision.advance_watermark_only,
                )
            continue
        if connection.dataset == "revenue":
            if action == "create":
                create_imported(session, company, connection, company_user, row, batch.id, at)
            elif action == "revise":
                revise_imported(session, company, connection, company_user, row, at)
            elif action == "link":
                link_imported(session, company, connection, row, at)
            else:
                continue
        elif connection.dataset == "plan":
            if action == "create":
                create_plan_row(session, company, connection, company_user, row, batch.id, at)
            elif action == "revise":
                revise_plan_row(session, company, connection, company_user, row, at)
            else:
                continue
        elif connection.dataset == "budget":
            if action == "create":
                create_budget_row(session, company, connection, company_user, row, batch.id, at)
            elif action == "revise":
                revise_budget_row(session, company, connection, company_user, row, at)
            else:
                continue
        else:
            if action == "create":
                _create_row(session, company, connection, company_user, row, at)
            elif action == "revise":
                _revise_row(session, company, connection, company_user, row, at)
            elif action == "link":
                _link_row(session, company, connection, company_user, row, at)
            else:
                continue
        committed += 1
        identity = load_identity_slot(session, company, connection.namespace, row.external_id)
        if identity is not None:
            apply_identity_watermark(
                identity,
                source_revision=row.source_revision,
                payload_hash=row.payload_hash,
                advance_only=False,
            )
    return committed, pending, has_review


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
            "new": counts.get("new", 0),
            "repeated": counts.get("repeated", 0),
            "changed": counts.get("changed", 0),
            "invalid": counts.get("invalid", 0),
            "ambiguous": counts.get("ambiguous", 0),
            "linked": counts.get("linked", 0),
            "unpost": counts.get("unpost", 0),
        },
        "rows": [
            row_preview_public(item) if balances else _row_preview_default(item) for item in rows
        ],
    }
    if balances:
        payload.update(batch_preview_public(batch, rows))
    return payload


def _row_preview_default(item: RawImportRow) -> dict:
    normalized = item.normalized_payload or {}
    return {
        "row_number": item.row_number,
        "external_id": item.external_id,
        "source_revision": item.source_revision,
        "operation": item.operation,
        "duplicate_status": item.duplicate_status,
        "proposed_action": item.proposed_action,
        "review_reason": normalized.get("review_reason"),
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


def _has_rule_condition(conditions: dict) -> bool:
    for key, raw in conditions.items():
        if key not in CONDITION_KEYS:
            continue
        if key in {"amount_min", "amount_max"}:
            if raw is not None and str(raw).strip() != "":
                return True
            continue
        if raw is not None and str(raw).strip() != "":
            return True
    return False


def _as_view(rule: ClassificationRule) -> RuleView:
    return RuleView(
        rule.priority,
        rule.enabled,
        dict(rule.conditions_json),
        str(rule.actions_json.get("category_code") or ""),
    )


def _load_company_rule(
    session: Session,
    company: Company,
    rule_id: uuid.UUID,
) -> ClassificationRule:
    rule = session.get(ClassificationRule, rule_id)
    if rule is None or rule.tenant_id != company.tenant_id:
        raise AppError(404, "not_found", "Правило не найдено")
    if rule.company_id is not None and rule.company_id != company.id:
        raise AppError(404, "not_found", "Правило не найдено")
    return rule


def _rule_match_payload(tx: CashTransaction, category_code: str) -> dict:
    return {
        "transaction_id": str(tx.id),
        "description": tx.description,
        "category_code": category_code,
    }


def _rule_transaction_outcome(
    view: RuleView,
    all_rules: tuple[RuleView, ...],
    tx: CashTransaction,
) -> str:
    if not _rule_matches_view(view, tx):
        return "no_match"
    winner = matching_category(
        all_rules,
        description=tx.description or "",
        counterparty_inn=tx.counterparty_inn or "",
        direction=tx.direction,
        amount=tx.amount,
    )
    if winner != view.category_code:
        return "higher_priority"
    if tx.locked_classification:
        return "locked"
    if tx.category_id is not None:
        return "categorized"
    return "eligible"


def _rule_matches_view(view: RuleView, tx: CashTransaction) -> bool:
    return (
        matching_category(
            (view,),
            description=tx.description or "",
            counterparty_inn=tx.counterparty_inn or "",
            direction=tx.direction,
            amount=tx.amount,
        )
        is not None
    )


def _posted_transaction_batches(
    session: Session,
    company: Company,
    *,
    after_date=None,
    after_id: uuid.UUID | None = None,
):
    cursor_date = after_date
    cursor_id = after_id
    while True:
        query = (
            select(CashTransaction)
            .where(
                CashTransaction.tenant_id == company.tenant_id,
                CashTransaction.company_id == company.id,
                CashTransaction.status == "posted",
            )
            .order_by(CashTransaction.business_date, CashTransaction.id)
            .limit(RULE_TX_FETCH_BATCH)
        )
        if cursor_id is not None:
            query = query.where(
                or_(
                    CashTransaction.business_date > cursor_date,
                    and_(
                        CashTransaction.business_date == cursor_date,
                        CashTransaction.id > cursor_id,
                    ),
                )
            )
        rows = session.scalars(query).all()
        if not rows:
            break
        yield rows
        last = rows[-1]
        cursor_date = last.business_date
        cursor_id = last.id


def _posted_transactions_remain(
    session: Session,
    company: Company,
    after_date,
    after_id: uuid.UUID,
) -> bool:
    found = session.scalar(
        select(CashTransaction.id)
        .where(
            CashTransaction.tenant_id == company.tenant_id,
            CashTransaction.company_id == company.id,
            CashTransaction.status == "posted",
            or_(
                CashTransaction.business_date > after_date,
                and_(
                    CashTransaction.business_date == after_date,
                    CashTransaction.id > after_id,
                ),
            ),
        )
        .limit(1)
    )
    return found is not None


def _rule_updated_audit(
    session: Session,
    user: User,
    tenant_id: uuid.UUID,
    rule_id: uuid.UUID,
    rule: ClassificationRule,
    at: datetime,
) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user.id,
            action="rule_updated",
            entity_type="classification_rule",
            entity_id=rule_id,
            before_redacted=None,
            after_redacted={
                "enabled": rule.enabled,
                "priority": rule.priority,
                "name": rule.name,
                "version": rule.version,
            },
            request_id=None,
            created_at=at,
        )
    )


def _rule_apply_audit(
    session: Session,
    user: User,
    tenant_id: uuid.UUID,
    rule_id: uuid.UUID,
    counters: dict,
    at: datetime,
) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            user_id=user.id,
            action="rule_applied",
            entity_type="classification_rule",
            entity_id=rule_id,
            before_redacted=None,
            after_redacted={
                "applied": counters["applied"],
                "skipped_locked": counters["skipped_locked"],
                "skipped_categorized": counters["skipped_categorized"],
                "skipped_higher_priority": counters["skipped_higher_priority"],
                "total_matches": counters["total_matches"],
                "has_more": counters["has_more"],
            },
            request_id=None,
            created_at=at,
        )
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


def _is_import_batch_file_uq(exc: IntegrityError) -> bool:
    orig = exc.orig
    if orig is None:
        return False
    diag = getattr(orig, "diag", None)
    if diag is not None and getattr(diag, "constraint_name", None) == "import_batches_file_uq":
        return True
    return "import_batches_file_uq" in str(orig)


def _batch_after_file_uq_conflict(
    session: Session,
    company: Company,
    connection: SourceConnection,
    digest: str,
) -> ImportBatch | None:
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        found = session.scalar(
            select(ImportBatch).where(
                ImportBatch.tenant_id == company.tenant_id,
                ImportBatch.company_id == company.id,
                ImportBatch.connection_id == connection.id,
                ImportBatch.file_hash == digest,
            )
        )
        if found is not None:
            return found
        time.sleep(0.02)
    return None


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
