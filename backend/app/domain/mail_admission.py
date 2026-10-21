"""Политика допуска входящего письма к preview (FA-R04.1).

Gate не создаёт delivery, batch или финансовые записи.
Доверие транспорта задаётся только явным TrustedTransportAuth (адаптер/fixture),
не заголовками письма и не публичным запросом.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from email.utils import getaddresses
from enum import StrEnum
from uuid import UUID

from app.services.auth_service import normalize_email

_AUTH_RESULTS_PASS = re.compile(
    r"\b(spf|dkim|dmarc)\s*=\s*pass\b",
    re.IGNORECASE,
)


class MailAdmissionOutcome(StrEnum):
    ALLOW_PREVIEW = "allow_preview"
    REJECT = "reject"
    REVIEW = "review"


@dataclass(frozen=True)
class MailAddress:
    addr_spec: str
    display_name: str | None = None


@dataclass(frozen=True)
class UntrustedMailEnvelope:
    """Сведения из письма — не доказательство доверия."""

    from_header: str
    reply_to_header: str | None = None
    authentication_results_header: str | None = None


@dataclass(frozen=True)
class TrustedTransportAuth:
    """Результаты аутентификации от доверенного транспорта (fixture/адаптер)."""

    message_authenticated: bool
    spf: str
    dkim: str
    dmarc: str


@dataclass(frozen=True)
class TrustedServerBinding:
    """Серверная привязка маршрута; письмо её не выбирает."""

    connection_id: UUID
    tenant_id: UUID
    company_id: UUID
    actor_user_id: UUID


@dataclass(frozen=True)
class MailAdmissionContext:
    tenant_id: UUID
    company_id: UUID
    connection_id: UUID
    actor_user_id: UUID
    sender_normalized: str


@dataclass(frozen=True)
class MailAdmissionDecision:
    outcome: MailAdmissionOutcome
    reason_code: str
    context: MailAdmissionContext | None = None


@dataclass(frozen=True)
class PolicyProceed:
    sender_normalized: str


@dataclass(frozen=True)
class PolicyStop:
    decision: MailAdmissionDecision


def parse_from_header(raw: str) -> tuple[MailAddress, ...]:
    pairs = getaddresses([raw or ""])
    parsed: list[MailAddress] = []
    for display_name, addr in pairs:
        if not addr.strip():
            continue
        parsed.append(MailAddress(addr_spec=addr.strip(), display_name=display_name or None))
    return tuple(parsed)


def parse_address_list(raw: str | None) -> tuple[str, ...]:
    if raw is None or not raw.strip():
        return ()
    pairs = getaddresses([raw])
    return tuple(addr.strip().lower() for _name, addr in pairs if addr.strip())


def _reject(reason_code: str) -> PolicyStop:
    return PolicyStop(
        MailAdmissionDecision(
            outcome=MailAdmissionOutcome.REJECT,
            reason_code=reason_code,
            context=None,
        )
    )


def _review(reason_code: str) -> PolicyStop:
    return PolicyStop(
        MailAdmissionDecision(
            outcome=MailAdmissionOutcome.REVIEW,
            reason_code=reason_code,
            context=None,
        )
    )


def _transport_passes(transport: TrustedTransportAuth) -> bool:
    return (
        transport.message_authenticated
        and transport.spf == "pass"
        and transport.dkim == "pass"
        and transport.dmarc == "pass"
    )


def _header_claims_auth_pass(header: str | None) -> bool:
    if not header:
        return False
    return _AUTH_RESULTS_PASS.search(header) is not None


def reject_sender_identity_mismatch(
    sender_normalized: str,
    actor_normalized_email: str,
) -> PolicyStop | None:
    if sender_normalized == actor_normalized_email:
        return None
    return _reject("sender_not_verified_user")


def apply_mail_admission_policy(
    envelope: UntrustedMailEnvelope,
    transport: TrustedTransportAuth | None,
) -> PolicyProceed | PolicyStop:
    if transport is None:
        return _reject("transport_evidence_missing")

    header_claims_pass = _header_claims_auth_pass(envelope.authentication_results_header)
    transport_ok = _transport_passes(transport)

    if header_claims_pass and not transport_ok:
        return _reject("forged_authentication_results")

    if not transport.message_authenticated:
        return _reject("transport_not_authenticated")

    if not transport_ok:
        return _reject("transport_auth_failed")

    from_addresses = parse_from_header(envelope.from_header)
    if not from_addresses:
        return _reject("sender_missing")
    if len(from_addresses) > 1:
        return _review("ambiguous_sender")

    sole_from = from_addresses[0]
    sender_normalized = normalize_email(sole_from.addr_spec)
    if not sender_normalized or "@" not in sender_normalized:
        return _reject("sender_missing")

    return PolicyProceed(sender_normalized=sender_normalized)
