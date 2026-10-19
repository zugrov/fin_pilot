"""Session User Transport API (FA-R02.3) — envelope и ответ."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SESSION_SCHEMA_VERSION = "1.0-session"
ALLOWED_ENVELOPE_KEYS = frozenset(
    {"schema_version", "delivery_key", "connection_id", "channel", "parts"}
)
ALLOWED_PART_KEYS = frozenset({"part_index", "dataset", "format", "content_sha256"})


class SessionIngestPartMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    part_index: int = Field(ge=1)
    dataset: Literal["cash", "revenue", "plan", "budget", "balances"]
    format: Literal["csv", "xlsx", "clientbank"]
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class SessionIngestEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0-session"]
    delivery_key: str = Field(min_length=1, max_length=128)
    connection_id: UUID
    channel: Literal["ui"]
    parts: list[SessionIngestPartMeta] = Field(min_length=1)


class SessionIngestPartLinks(BaseModel):
    preview: str
    errors: str


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
    parts: list[SessionIngestPartResponse]


def reject_unknown_json_keys(raw: dict, allowed: frozenset[str], *, label: str) -> None:
    extra = set(raw) - allowed
    if extra:
        names = ", ".join(sorted(extra))
        raise ValueError(f"Неподдерживаемые поля {label}: {names}")


def parse_envelope_json(raw_text: str) -> SessionIngestEnvelope:
    import json

    from app.errors import AppError

    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise AppError(422, "validation_error", "Envelope должен быть JSON") from exc
    if not isinstance(data, dict):
        raise AppError(422, "validation_error", "Envelope должен быть объектом")
    try:
        reject_unknown_json_keys(data, ALLOWED_ENVELOPE_KEYS, label="envelope")
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
        return SessionIngestEnvelope.model_validate(data)
    except Exception as exc:
        raise AppError(422, "validation_error", "Некорректный envelope") from exc
