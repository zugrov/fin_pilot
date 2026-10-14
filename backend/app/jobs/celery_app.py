from collections.abc import Callable
from datetime import UTC, datetime

from celery import Celery
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.integrations.payments import build_payment_provider
from app.services.billing_service import (
    enqueue_renewal_reminders,
    process_inbox,
    reconcile_open_payments,
)


def make_celery() -> Celery:
    settings = get_settings()
    app = Celery("finpilot", broker=settings.redis_url, backend=settings.redis_url)
    app.conf.beat_schedule = {
        "process-inbox": {"task": "billing.process_inbox", "schedule": 30.0},
        "reconcile-payments": {"task": "billing.reconcile", "schedule": 60.0},
        "renewal-reminders": {"task": "billing.reminders", "schedule": 3600.0},
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
