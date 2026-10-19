"""Session User Transport API (FA-R02.3 / FA-R02.4) — envelope и ответ."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

SESSION_SCHEMA_V10 = "1.0-session"
SESSION_SCHEMA_V11 = "1.1-session"

ALLOWED_ENVELOPE_KEYS_V10 = frozenset(
    {"schema_version", "delivery_key", "connection_id", "channel", "parts"}
)
ALLOWED_ENVELOPE_KEYS_V11 = ALLOWED_ENVELOPE_KEYS_V10 | frozenset(
    {
        "mode",
        "period_from",
        "period_to",
        "control_totals",
        "completeness_claim",
    }
)
ALLOWED_PART_KEYS = frozenset({"part_index", "dataset", "format", "content_sha256"})


class SessionIngestPartMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_index: int = Field(ge=1)
    dataset: Literal["cash", "revenue", "plan", "budget", "balances"]
    format: Literal["csv", "xlsx", "clientbank"]
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class SessionControlTotals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    record_count: int = Field(ge=0)
    currency: str | None = None
    cash_in: str | None = None
    cash_out: str | None = None
    revenue_net: str | None = None


class SessionCompletenessClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    through: date
    scope: Literal["explicit-dataset", "explicit-period"] = "explicit-dataset"


class SessionIngestEnvelopeV10(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0-session"]
    delivery_key: str = Field(min_length=1, max_length=128)
    connection_id: UUID
    channel: Literal["ui"]
    parts: list[SessionIngestPartMeta] = Field(min_length=1)


class SessionIngestEnvelopeV11(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.1-session"]
    delivery_key: str = Field(min_length=1, max_length=128)
    connection_id: UUID
    channel: Literal["ui"]
    parts: list[SessionIngestPartMeta] = Field(min_length=1)
    mode: Literal["delta", "snapshot"]
    period_from: date
    period_to: date
    control_totals: SessionControlTotals | None = None
    completeness_claim: SessionCompletenessClaim | None = None

    @field_validator("period_to")
    @classmethod
    def period_order(cls, period_to: date, info) -> date:
        start = info.data.get("period_from")
        if start is not None and period_to < start:
            raise ValueError("period_to раньше period_from")
        return period_to


@dataclass(frozen=True)
class ParsedSessionEnvelope:
    schema_version: str
    delivery_key: str
    connection_id: UUID
    channel: str
    parts: list[SessionIngestPartMeta]
    mode: str | None
    period_from: date | None
    period_to: date | None
    control_totals: dict[str, Any] | None
    completeness_claim: dict[str, Any] | None
    raw_metadata: dict[str, Any]


class SessionIngestPartLinks(BaseModel):
    preview: str
    errors: str
    commit: str | None = None


class SessionIngestPartResponse(BaseModel):
    part_index: int
    state: str
    error_code: str | None = None
    batch_id: str | None = None
    batch_status: str | None = None
    links: SessionIngestPartLinks | None = None


class SessionIngestDeliveryResponse(BaseModel):
    delivery_id: str
    transport_status: str
    validation_status: str
    validation_block_reasons: list[str]
    control_totals: dict[str, Any] | None = None
    parts: list[SessionIngestPartResponse]


def reject_unknown_json_keys(raw: dict, allowed: frozenset[str], *, label: str) -> None:
    extra = set(raw) - allowed
    if extra:
        names = ", ".join(sorted(extra))
        raise ValueError(f"Неподдерживаемые поля {label}: {names}")


def parse_envelope_json(raw_text: str) -> ParsedSessionEnvelope:
    from app.errors import AppError

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AppError(422, "validation_error", "Envelope должен быть JSON") from exc
    if not isinstance(data, dict):
        raise AppError(422, "validation_error", "Envelope должен быть объектом")
    version = data.get("schema_version")
    if version == SESSION_SCHEMA_V10:
        allowed = ALLOWED_ENVELOPE_KEYS_V10
    elif version == SESSION_SCHEMA_V11:
        allowed = ALLOWED_ENVELOPE_KEYS_V11
    else:
        raise AppError(422, "validation_error", "Неподдерживаемая schema_version")
    try:
        reject_unknown_json_keys(data, allowed, label="envelope")
    except ValueError as exc:
        raise AppError(422, "validation_error", str(exc)) from exc
    parts_raw = data.get("parts")
    if not isinstance(parts_raw, list):
        raise AppError(422, "validation_error", "parts должен быть массивом")
    for index, item in enumerate(parts_raw):
        if not isinstance(item, dict):
            raise AppError(422, "validation_error", f"parts[{index}] должен быть объектом")
        try:
            reject_unknown_json_keys(item, ALLOWED_PART_KEYS, label=f"parts[{index}]")
        except ValueError as exc:
            raise AppError(422, "validation_error", str(exc)) from exc
    try:
        if version == SESSION_SCHEMA_V10:
            envelope_v10 = SessionIngestEnvelopeV10.model_validate(data)
            return ParsedSessionEnvelope(
                schema_version=envelope_v10.schema_version,
                delivery_key=envelope_v10.delivery_key,
                connection_id=envelope_v10.connection_id,
                channel=envelope_v10.channel,
                parts=envelope_v10.parts,
                mode=None,
                period_from=None,
                period_to=None,
                control_totals=None,
                completeness_claim=None,
                raw_metadata=dict(data),
            )
        envelope_v11 = SessionIngestEnvelopeV11.model_validate(data)
        if envelope_v11.mode == "snapshot" and envelope_v11.control_totals is None:
            raise AppError(
                422,
                "validation_error",
                "Snapshot требует control_totals с record_count",
            )
        control = (
            None
            if envelope_v11.control_totals is None
            else envelope_v11.control_totals.model_dump()
        )
        completeness = (
            None
            if envelope_v11.completeness_claim is None
            else envelope_v11.completeness_claim.model_dump(mode="json")
        )
        return ParsedSessionEnvelope(
            schema_version=envelope_v11.schema_version,
            delivery_key=envelope_v11.delivery_key,
            connection_id=envelope_v11.connection_id,
            channel=envelope_v11.channel,
            parts=envelope_v11.parts,
            mode=envelope_v11.mode,
            period_from=envelope_v11.period_from,
            period_to=envelope_v11.period_to,
            control_totals=control,
            completeness_claim=completeness,
            raw_metadata=dict(data),
        )
    except AppError:
        raise
    except Exception as exc:
        raise AppError(422, "validation_error", "Некорректный envelope") from exc
