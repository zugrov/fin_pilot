from collections.abc import Callable
from datetime import UTC, datetime

from celery import Celery
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.integrations.email import build_email_provider
from app.integrations.payments import build_payment_provider
from app.jobs.finance import dispatch_outbox
from app.services.billing_service import (
    enqueue_renewal_reminders,
    process_inbox,
    reconcile_open_payments,
)
from app.services.telegram_digest import schedule_digests
from app.services.telegram_dispatch import dispatch_outbox as dispatch_telegram


def make_celery() -> Celery:
    settings = get_settings()
    app = Celery("finpilot", broker=settings.redis_url, backend=settings.redis_url)
    app.conf.beat_schedule = {
        "process-inbox": {"task": "billing.process_inbox", "schedule": 30.0},
        "reconcile-payments": {"task": "billing.reconcile", "schedule": 60.0},
        "renewal-reminders": {"task": "billing.reminders", "schedule": 3600.0},
        "dispatch-outbox": {"task": "mail.dispatch_outbox", "schedule": 30.0},
        "telegram-schedule": {"task": "telegram.schedule_digests", "schedule": 60.0},
        "telegram-dispatch": {"task": "telegram.dispatch_outbox", "schedule": 30.0},
    }
    app.conf.timezone = "Europe/Moscow"
    return app


celery_app = make_celery()


def _run(work: Callable[[Session, Settings], int]) -> int:
    settings = get_settings()
    engine = create_engine(settings.worker_database_url)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        result = work(session, settings)
        session.commit()
        return result
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
        engine.dispose()


@celery_app.task(name="billing.process_inbox")
def process_inbox_task() -> int:
    def work(session: Session, settings: Settings) -> int:
        provider = build_payment_provider(settings)
        return process_inbox(session, provider, settings, datetime.now(UTC))

    return _run(work)


@celery_app.task(name="billing.reconcile")
def reconcile_task() -> int:
    def work(session: Session, settings: Settings) -> int:
        provider = build_payment_provider(settings)
        return reconcile_open_payments(session, provider, settings, datetime.now(UTC))

    return _run(work)


@celery_app.task(name="billing.reminders")
def reminders_task() -> int:
    def work(session: Session, settings: Settings) -> int:
        return enqueue_renewal_reminders(session, settings, datetime.now(UTC))

    return _run(work)


@celery_app.task(name="mail.dispatch_outbox")
def dispatch_outbox_task() -> int:
    def work(session: Session, settings: Settings) -> int:
        provider = build_email_provider(settings)
        return dispatch_outbox(session, settings, provider, datetime.now(UTC))

    return _run(work)


@celery_app.task(name="telegram.schedule_digests")
def schedule_digests_task() -> int:
    def work(session: Session, settings: Settings) -> int:
        from app.services.telegram_bot import poll_once

        poll_once(session, settings, datetime.now(UTC))
        return schedule_digests(session, settings, datetime.now(UTC))

    return _run(work)


@celery_app.task(name="telegram.dispatch_outbox")
def dispatch_telegram_task() -> int:
    def work(session: Session, settings: Settings) -> int:
        from app.integrations.telegram import build_transport

        return dispatch_telegram(session, settings, build_transport(settings), datetime.now(UTC))

    return _run(work)
