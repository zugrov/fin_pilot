import json
import secrets
import uuid
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from app.config import Settings
from app.domain.billing.periods import MOSCOW
from app.domain.money import money
from app.errors import AppError
from app.models.cash import CashCategory, Wallet
from app.models.identity import Membership, User
from app.models.revenue import Direction
from app.models.telegram import BotDraft, TelegramBinding
from app.security.access import companies_for, require_membership
from app.security.context import set_context
from app.security.tokens import hash_token
from app.services.cash_service import (
    company_summary,
    create_transaction,
    request_hash,
    summary_payload,
)
from app.services.report_service import revenue_snapshot
from app.services.telegram_binding import attach_pending, revoke_binding, subscription_view
from app.services.telegram_digest import queue_manual
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session
from sqlalchemy.sql import bindparam

DRAFT_TTL = timedelta(minutes=30)
POSTED_WALLETS = {"cash", "other", "business_owner_card"}
PENDING_TEXT = "Подтвердите привязку на сайте. Финансовые данные не отправлены."
ACCOUNTING = "Это запись учёта, не банковский платёж."


def ingest_update(session: Session, settings: Settings, update: dict, at) -> list[dict]:
    update_id = int(update["update_id"])
    row_id = uuid.uuid4()
    bot_id = "local" if not settings.bot_token else hash_token(settings.bot_token)[:16]
    inserted = session.execute(
        text(
            "SELECT app_record_telegram_update(:id, :bot, :update_id, :digest, :payload, :at)"
        ).bindparams(bindparam("payload", type_=JSONB)),
        {
            "id": row_id,
            "bot": bot_id,
            "update_id": update_id,
            "digest": hash_token(json.dumps(update, sort_keys=True, default=str)),
            "payload": update,
            "at": at,
        },
    ).scalar()
    if not inserted:
        return []
    replies, tenant_id, status = _handle(session, settings, update, at)
    session.execute(
        text("SELECT app_finish_telegram_update(:id, :status, :tenant)"),
        {"id": row_id, "status": status, "tenant": tenant_id},
    )
    return replies


def poll_once(session: Session, settings: Settings, at) -> int:
    from app.integrations.telegram import polling_allowed

    if not polling_allowed(settings):
        return 0
    _ = (session, at)
    return 0


def _handle(session, settings, update: dict, at) -> tuple[list[dict], uuid.UUID | None, str]:
    if "callback_query" in update:
        return _on_callback(session, settings, update["callback_query"], at)
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    if chat.get("type") != "private":
        return [], None, "ignored"
    sender = message.get("from") or {}
    text_value = str(message.get("text") or "").strip()
    telegram_user_id = int(sender.get("id") or 0)
    chat_id = int(chat.get("id") or 0)
    if text_value.startswith("/"):
        return _on_command(session, settings, text_value, telegram_user_id, chat_id, at)
    return _on_text(session, settings, text_value, telegram_user_id, at)


def _on_command(session, settings, raw: str, telegram_user_id: int, chat_id: int, at):
    name, arg = _split_command(raw)
    if name == "/start":
        return _start(session, arg, telegram_user_id, chat_id, at)
    binding = _binding(session, telegram_user_id)
    if binding is None:
        return [ _say("Сначала привяжите бота на сайте.") ], None, "processed"
    user, membership = _actor(session, binding)
    if name == "/stop":
        revoke_binding(session, binding, at)
        return [_say("Рассылка отключена, очередь отменена.")], binding.tenant_id, "processed"
    if name == "/help":
        return [_say(_help())], binding.tenant_id, "processed"
    if name == "/settings":
        return [_say(_settings_text(session, membership, user))], binding.tenant_id, "processed"
    if binding.status != "active":
        return [_say(PENDING_TEXT)], binding.tenant_id, "processed"
    if name == "/add":
        return _begin_add(session, settings, binding, user, membership, at)
    if name == "/summary":
        return _summary(session, settings, membership, user, at, raw)
    handler = {
        "/companies": _companies,
        "/balance": _balance,
        "/forecast": _forecast,
        "/revenue": _revenue,
        "/budget": _budget,
        "/alerts": _alerts,
        "/sources": _sources,
    }.get(name)
    if handler is None:
        return [_say("Неизвестная команда. /help")], binding.tenant_id, "processed"
    try:
        text_value = handler(session, settings, membership, user, at)
    except AppError as exc:
        text_value = exc.message
    return [_say(text_value)], binding.tenant_id, "processed"


def _start(session, token: str, telegram_user_id: int, chat_id: int, at):
    if not token:
        return [_say(_help())], None, "processed"
    found = session.execute(
        text("SELECT * FROM app_consume_link_token(:digest, :at)"),
        {"digest": hash_token(token), "at": at},
    ).mappings().first()
    if found is None:
        return [_say("Ссылка недействительна или уже использована.")], None, "processed"
    existing = session.execute(
        text("SELECT * FROM app_binding_by_telegram(:telegram_user)"),
        {"telegram_user": telegram_user_id},
    ).mappings().first()
    if existing is not None and existing["binding_user_id"] != found["token_user_id"]:
        return [_say("Этот Telegram уже привязан к другому пользователю.")], None, "processed"
    if (
        existing is not None
        and existing["binding_status"] == "active"
        and existing["binding_user_id"] == found["token_user_id"]
    ):
        return [_say("Привязка уже подтверждена.")], found["token_tenant_id"], "processed"
    attach_pending(
        session,
        tenant_id=found["token_tenant_id"],
        user_id=found["token_user_id"],
        telegram_user_id=telegram_user_id,
        chat_id=chat_id,
        at=at,
    )
    return [_say(PENDING_TEXT)], found["token_tenant_id"], "processed"


def _begin_add(session, settings, binding, user, membership, at):
    companies = _writable(session, settings, membership, user, at)
    if isinstance(companies, str):
        return [_say(companies)], binding.tenant_id, "processed"
    _close_drafts(session, binding, at)
    draft = BotDraft(
        tenant_id=binding.tenant_id,
        binding_id=binding.id,
        state="company",
        payload={"callbacks": {}},
        expires_at=at + DRAFT_TTL,
        idempotency_key=None,
        created_at=at,
        updated_at=at,
    )
    session.add(draft)
    session.flush()
    if len(companies) == 1:
        draft.payload = {**draft.payload, "company_id": str(companies[0].id)}
        draft.state = "direction"
        return [_direction_prompt(draft)], binding.tenant_id, "processed"
        options = [(item.name, str(item.id)) for item in companies]
        reply = _choice(draft, "Выберите фирму", options, "company")
        return [reply], binding.tenant_id, "processed"


def _on_callback(session, settings, query: dict, at):
    sender = int((query.get("from") or {}).get("id") or 0)
    binding = _binding(session, sender)
    if binding is None or binding.status != "active":
        tenant = None if binding is None else binding.tenant_id
        return [_say(PENDING_TEXT)], tenant, "processed"
    token = str(query.get("data") or "")
    draft = _draft_for_token(session, binding, token, at)
    if draft is None:
        return [_say("Кнопка устарела.")], binding.tenant_id, "processed"
    action = (draft.payload.get("callbacks") or {}).get(token)
    if not action:
        return [_say("Кнопка устарела.")], binding.tenant_id, "processed"
    user, membership = _actor(session, binding)
    return _apply_choice(session, settings, draft, binding, user, membership, action, at)


def _on_text(session, settings, value: str, telegram_user_id: int, at):
    binding = _binding(session, telegram_user_id)
    if binding is None or binding.status != "active":
        tenant = None if binding is None else binding.tenant_id
        message = PENDING_TEXT if binding else "Сначала привяжите бота на сайте."
        return [_say(message)], tenant, "processed"
    draft = _open_draft(session, binding, at)
    if draft is None:
        return [_say("Нет открытого ввода. /add")], binding.tenant_id, "processed"
    user, membership = _actor(session, binding)
    if draft.state == "amount":
        parsed = _amount(value)
        if parsed is None:
            return [_say("Введите сумму, например 1000,50")], binding.tenant_id, "processed"
        draft.payload = {**draft.payload, "amount": format(parsed, "f")}
        draft.state = "date"
        draft.updated_at = at
        return [_say("Дата операции. Пусто или «сегодня» — местный день.")], binding.tenant_id, (
            "processed"
        )
    if draft.state == "date":
        parsed_date = _date(value, at)
        if parsed_date is None:
            return [_say("Дата в формате ГГГГ-ММ-ДД или ДД.ММ.ГГГГ")], binding.tenant_id, (
                "processed"
            )
        draft.payload = {**draft.payload, "business_date": parsed_date.isoformat()}
        draft.state = "category"
        draft.updated_at = at
        return [_say("Категория: код, название или «без категории».")], binding.tenant_id, (
            "processed"
        )
    if draft.state == "category":
        return _take_category(session, draft, binding, value, at)
    if draft.state == "flow":
        return _take_flow(session, draft, binding, value, at)
    if draft.state == "comment":
        comment = "" if value.casefold() == "пропустить" else value
        draft.payload = {**draft.payload, "comment": comment}
        draft.state = "preview"
        draft.updated_at = at
        return [_preview(draft)], binding.tenant_id, "processed"
    _ = (settings, user, membership)
    return [_say("Используйте кнопки или /add")], binding.tenant_id, "processed"


def _apply_choice(session, settings, draft, binding, user, membership, action, at):
    kind = action["kind"]
    value = action["value"]
    if kind == "company":
        draft.payload = {**draft.payload, "company_id": value}
        draft.state = "direction"
    elif kind == "direction":
        draft.payload = {**draft.payload, "direction": value}
        draft.state = "wallet"
        return _wallet_prompt(session, draft, binding, at)
    elif kind == "wallet":
        draft.payload = {**draft.payload, "wallet_id": value}
        draft.state = "amount"
        draft.updated_at = at
        return [_say("Сумма. Можно с пробелами и запятой.")], binding.tenant_id, "processed"
    elif kind == "confirm":
        return _confirm(session, settings, draft, binding, user, membership, at)
    elif kind == "cancel":
        draft.state = "cancelled"
        draft.updated_at = at
        return [_say("Ввод отменён.")], binding.tenant_id, "processed"
    draft.updated_at = at
    if draft.state == "direction":
        return [_direction_prompt(draft)], binding.tenant_id, "processed"
    return [_say("Шаг не распознан.")], binding.tenant_id, "processed"


def _confirm(session, settings, draft, binding, user, membership, at):
    if draft.state == "done" and draft.payload.get("transaction_id"):
        return [_say(_saved_text(draft))], binding.tenant_id, "processed"
    company = next(
        (
            item
            for item in companies_for(session, membership)
            if str(item.id) == draft.payload["company_id"]
        ),
        None,
    )
    wallet = session.get(Wallet, uuid.UUID(draft.payload["wallet_id"]))
    if company is None or wallet is None or wallet.company_id != company.id:
        return [_say("Кошелёк не найден")], binding.tenant_id, "processed"
    tx_status = "posted" if wallet.type in POSTED_WALLETS else "draft"
    key = f"telegram-draft:{draft.id}"
    body = {
        "wallet_id": str(wallet.id),
        "business_date": draft.payload["business_date"],
        "direction": draft.payload["direction"],
        "amount": draft.payload["amount"],
        "status": tx_status,
        "source": "telegram",
    }
    from datetime import date as date_cls

    _status, payload = create_transaction(
        session,
        membership,
        company,
        user,
        wallet_id=wallet.id,
        business_date=date_cls.fromisoformat(draft.payload["business_date"]),
        occurred_at=None,
        direction=draft.payload["direction"],
        amount=Decimal(draft.payload["amount"]),
        category_id=_optional_uuid(draft.payload.get("category_id")),
        description=draft.payload.get("comment") or "",
        status=tx_status,
        idempotency_key=key,
        request_hash=request_hash(body),
        at=at,
        source="telegram",
    )
    draft.state = "done"
    draft.idempotency_key = key
    draft.payload = {**draft.payload, "transaction_id": payload["id"], "tx_status": tx_status}
    draft.updated_at = at
    _ = settings
    return [_say(_saved_text(draft))], binding.tenant_id, "processed"


def _summary(session, settings, membership, user, at, raw: str):
    from app.services.telegram_digest import render_parts

    request_id = f"summary:{hash_token(raw + at.isoformat())[:24]}"
    try:
        snapshot = queue_manual(
            session, membership, user, settings, request_id=request_id, at=at
        )
    except AppError as exc:
        return [_say(exc.message)], membership.tenant_id, "processed"
    text_value = "\n\n".join(render_parts(snapshot.metrics_json, settings.public_base_url))
    return [_say(text_value)], membership.tenant_id, "processed"


def _companies(session, settings, membership, user, at) -> str:
    _ = (settings, at)
    names = [item.name for item in companies_for(session, membership)]
    if not names:
        return "Нет фирм в зоне доступа"
    return "Фирмы: " + ", ".join(names)


def _balance(session, settings, membership, user, at) -> str:
    lines = []
    for company in _readable(session, settings, membership, user, at):
        moment = at
        summary = summary_payload(company_summary(session, company, moment))
        lines.append(f"{company.name}: остаток {_none(summary['cash_total'])}")
    return "\n".join(lines) or "Нет фирм в зоне доступа"


def _forecast(session, settings, membership, user, at) -> str:
    from app.services import forecast_service

    lines = []
    for company in _readable(session, settings, membership, user, at):
        view = forecast_service.company_forecast(
            session, company, at.astimezone(MOSCOW).date(), "base", at
        )
        gap = view.get("gap_amount")
        lines.append(f"{company.name}: дефицит {_none(gap)}")
    return "\n".join(lines) or "Нет фирм в зоне доступа"


def _revenue(session, settings, membership, user, at) -> str:
    lines = []
    day = at.astimezone(MOSCOW).date()
    for company in _readable(session, settings, membership, user, at):
        view = revenue_snapshot(session, company.id, company.tenant_id, (day, day))
        lines.append(f"{company.name}: выручка {_none(view['amount'])}")
    return "\n".join(lines) or "Нет фирм в зоне доступа"


def _budget(session, settings, membership, user, at) -> str:
    from app.services import budget_service

    lines = []
    for company in _readable(session, settings, membership, user, at):
        view = budget_service.plan_fact(session, company, at.astimezone(MOSCOW).date())
        lines.append(f"{company.name}: план-факт {view['bases'][0]['status']}")
    return "\n".join(lines) or "Нет фирм в зоне доступа"


def _alerts(session, settings, membership, user, at) -> str:
    from app.services import alert_service

    lines = []
    for company in _readable(session, settings, membership, user, at):
        view = alert_service.evaluate(session, company, at.astimezone(MOSCOW).date(), at)
        opened = [item for item in view["alerts"] if item["status"] != "resolved"]
        lines.append(f"{company.name}: открытых сигналов {len(opened)}")
    return "\n".join(lines) or "Нет фирм в зоне доступа"


def _sources(session, settings, membership, user, at) -> str:
    from app.services import import_service

    lines = []
    for company in _readable(session, settings, membership, user, at):
        sources = import_service.list_sources(session, company)
        if not sources:
            lines.append(f"{company.name}: источников нет")
            continue
        for source in sources:
            covered = source.get("coverage_through") or "нет данных"
            lines.append(f"{company.name}: {source['name']} покрытие {covered}")
    return "\n".join(lines) or "Нет фирм в зоне доступа"


def _readable(session, settings, membership, user, at):
    from app.services.telegram_digest import _can_read

    rows = []
    for company in companies_for(session, membership):
        if _can_read(session, membership, company, user, settings, at):
            rows.append(company)
    if not rows:
        raise AppError(402, "payment_required", "Нет оплаченного доступа к фирме")
    return rows


def _writable(session, settings, membership, user, at):
    from app.security.access import assert_finance_access

    allowed = []
    denied = None
    for company in companies_for(session, membership):
        try:
            assert_finance_access(
                session,
                membership=membership,
                company=company,
                user_verified=user.email_verified_at is not None,
                at=at,
                mode="write",
                grace_days=settings.billing_grace_days,
                bypass=settings.billing_bypass_allowed(),
            )
        except AppError as exc:
            denied = exc
            continue
        allowed.append(company)
    if allowed:
        return allowed
    if denied is not None:
        return denied.message
    return "Нет фирм в зоне доступа"


def _wallet_prompt(session, draft, binding, at):
    wallets = session.scalars(
        select(Wallet).where(
            Wallet.company_id == uuid.UUID(draft.payload["company_id"]),
            Wallet.is_active.is_(True),
        )
    ).all()
    draft.updated_at = at
    if not wallets:
        return [_say("Нет кошельков")], binding.tenant_id, "processed"
    return [
        _choice(
            draft, "Выберите кошелёк", [(item.name, str(item.id)) for item in wallets], "wallet"
        )
    ], binding.tenant_id, "processed"


def _direction_prompt(draft: BotDraft) -> dict:
    return _choice(draft, "Приход или расход", [("Приход", "in"), ("Расход", "out")], "direction")


def _choice(draft: BotDraft, title: str, options: list[tuple[str, str]], kind: str) -> dict:
    buttons = []
    callbacks = dict(draft.payload.get("callbacks") or {})
    for label, value in options:
        token = secrets.token_urlsafe(8)
        callbacks[token] = {"kind": kind, "value": value}
        buttons.append({"label": label, "data": token})
    draft.payload = {**draft.payload, "callbacks": callbacks}
    return _say(title, buttons)


def _take_category(session, draft, binding, value: str, at):
    if value.casefold() == "без категории":
        draft.payload = {**draft.payload, "category_id": None}
    else:
        found = session.scalar(
            select(CashCategory).where(
                CashCategory.tenant_id == binding.tenant_id,
                (CashCategory.code == value) | (CashCategory.name == value),
            )
        )
        if found is None:
            return [_say("Категория не найдена")], binding.tenant_id, "processed"
        draft.payload = {**draft.payload, "category_id": str(found.id)}
    draft.state = "flow"
    draft.updated_at = at
    return [_say("Направление: код, название или «пропустить».")], binding.tenant_id, "processed"


def _take_flow(session, draft, binding, value: str, at):
    if value.casefold() == "пропустить":
        draft.payload = {**draft.payload, "direction_id": None}
    else:
        found = session.scalar(
            select(Direction).where(
                Direction.company_id == uuid.UUID(draft.payload["company_id"]),
                (Direction.code == value) | (Direction.name == value),
            )
        )
        if found is None:
            return [_say("Направление не найдено")], binding.tenant_id, "processed"
        draft.payload = {**draft.payload, "direction_id": str(found.id)}
    draft.state = "comment"
    draft.updated_at = at
    return [_say("Комментарий или «пропустить».")], binding.tenant_id, "processed"


def _preview(draft: BotDraft) -> dict:
    text = "\n".join(
        [
            "Проверьте запись.",
            ACCOUNTING,
            f"Сумма {draft.payload.get('amount')}",
            f"Дата {draft.payload.get('business_date')}",
        ]
    )
    buttons = []
    callbacks = dict(draft.payload.get("callbacks") or {})
    for label, kind in (("Подтвердить", "confirm"), ("Отмена", "cancel")):
        token = secrets.token_urlsafe(8)
        callbacks[token] = {"kind": kind, "value": kind}
        buttons.append({"label": label, "data": token})
    draft.payload = {**draft.payload, "callbacks": callbacks}
    return _say(text, buttons)


def _saved_text(draft: BotDraft) -> str:
    if draft.payload.get("tx_status") == "draft":
        return f"Черновик записан и в остаток не входит. {ACCOUNTING}"
    return f"Операция проведена. {ACCOUNTING}"


def _draft_for_token(session, binding, token: str, at) -> BotDraft | None:
    current = _open_draft(session, binding, at)
    if current is not None and token in (current.payload.get("callbacks") or {}):
        return current
    rows = session.scalars(
        select(BotDraft)
        .where(BotDraft.binding_id == binding.id, BotDraft.state == "done")
        .order_by(BotDraft.updated_at.desc())
    ).all()
    for row in rows:
        if token in (row.payload.get("callbacks") or {}):
            return row
    return None


def _open_draft(session, binding, at) -> BotDraft | None:
    row = session.scalar(
        select(BotDraft).where(
            BotDraft.binding_id == binding.id,
            BotDraft.state.notin_(("done", "cancelled")),
        )
    )
    if row is None:
        return None
    if row.expires_at <= at:
        row.state = "cancelled"
        return None
    return row


def _close_drafts(session, binding, at) -> None:
    rows = session.scalars(
        select(BotDraft).where(
            BotDraft.binding_id == binding.id,
            BotDraft.state.notin_(("done", "cancelled")),
        )
    ).all()
    for row in rows:
        row.state = "cancelled"
        row.updated_at = at
    session.flush()


def _binding(session, telegram_user_id: int) -> TelegramBinding | None:
    found = session.execute(
        text("SELECT * FROM app_binding_by_telegram(:telegram_user)"),
        {"telegram_user": telegram_user_id},
    ).mappings().first()
    if found is None:
        return None
    set_context(session, tenant_id=found["binding_tenant_id"], user_id=found["binding_user_id"])
    return session.get(TelegramBinding, found["binding_id"])


def _actor(session, binding: TelegramBinding) -> tuple[User, Membership]:
    set_context(session, tenant_id=binding.tenant_id, user_id=binding.user_id)
    user = session.get(User, binding.user_id)
    if user is None:
        raise AppError(404, "not_found", "Пользователь не найден")
    membership = require_membership(session, user.id, binding.tenant_id)
    return user, membership


def _say(text: str, buttons: list[dict] | None = None) -> dict:
    return {"text": text, "protect_content": True, "buttons": buttons or []}


def _help() -> str:
    return (
        "Команды: /summary /balance /forecast /revenue /budget "
        "/alerts /sources /add /settings /stop"
    )


def _settings_text(session, membership, user) -> str:
    try:
        view = subscription_view(session, membership, user)
    except AppError:
        return "Подписка ещё не включена. Финансовые цифры здесь не показываются."
    return (
        f"Сводка {view['local_time']} {view['timezone']}, режим {view['mode']}, "
        f"приватность {view['privacy_level']}."
    )


def _split_command(raw: str) -> tuple[str, str]:
    parts = raw.split(maxsplit=1)
    name = parts[0].split("@", 1)[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    return name, arg


def _amount(raw: str) -> Decimal | None:
    cleaned = raw.replace(" ", "").replace("\u00a0", "").replace(",", ".")
    try:
        value = money(Decimal(cleaned))
    except (InvalidOperation, ValueError):
        return None
    if value <= 0:
        return None
    return value


def _date(raw: str, at):
    from datetime import date as date_cls

    text_value = raw.strip().casefold()
    if text_value in {"", "сегодня"}:
        return at.astimezone(MOSCOW).date()
    try:
        return date_cls.fromisoformat(text_value)
    except ValueError:
        pass
    pieces = text_value.split(".")
    if len(pieces) == 3:
        try:
            return date_cls(int(pieces[2]), int(pieces[1]), int(pieces[0]))
        except ValueError:
            return None
    return None


def _optional_uuid(raw: str | None):
    if not raw:
        return None
    return uuid.UUID(raw)


def _none(value) -> str:
    return "нет данных" if value is None else str(value)
