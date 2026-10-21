import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain.money import money

PART_LIMIT = 3500

# Русские названия типов сигналов для текста Telegram (не меняют расчёты и content_hash).
SIGNAL_TYPE_LABELS: dict[str, str] = {
    "cash_gap": "Дефицит денег",
    "reserve_breach": "Пробой резерва",
    "expense_overrun": "Перерасход",
    "revenue_shortfall": "Недобор выручки",
    "large_outgoing": "Крупный расход",
    "unusual_outgoing": "Нетипичный расход",
    "new_counterparty": "Новый контрагент",
    "duplicate_candidate": "Возможный дубликат",
    "stale_source": "Устаревший источник",
    "overdue_obligation": "Просроченное обязательство",
    "unclassified_share": "Доля без категории",
}

UNKNOWN_SIGNAL_LABEL = "Финансовый сигнал"

RESTRICTED_FUNDS_LABEL = "ограниченные средства"


def signal_type_label(rule_type: str) -> str:
    return SIGNAL_TYPE_LABELS.get(rule_type, UNKNOWN_SIGNAL_LABEL)


class SlotState(Enum):
    WAITING = "waiting"
    DUE = "due"
    MISSED = "missed"
    CLOSED = "closed"


def timezone_or_none(name: str) -> ZoneInfo | None:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return None


def local_to_utc(local_date: date, local_time: time, zone_name: str) -> datetime:
    """Несуществующее местное время сдвигается вперёд, повторяющееся берётся один раз."""
    zone = ZoneInfo(zone_name)
    naive = datetime.combine(local_date, local_time.replace(second=0, microsecond=0))
    if not _wall_exists(naive, zone):
        probe = naive
        for _ in range(180):
            probe += timedelta(minutes=1)
            if _wall_exists(probe, zone):
                return probe.replace(tzinfo=zone).astimezone(UTC_ZONE)
        raise ValueError("нет действительного местного времени")
    first = naive.replace(tzinfo=zone, fold=0).astimezone(UTC_ZONE)
    second = naive.replace(tzinfo=zone, fold=1).astimezone(UTC_ZONE)
    return min(first, second)


def slot_state(
    at: datetime, local_time: time, zone_name: str, days: list[int]
) -> tuple[SlotState, date]:
    zone = ZoneInfo(zone_name)
    local_date = at.astimezone(zone).date()
    if local_date.isoweekday() not in days:
        return SlotState.CLOSED, local_date
    slot = local_to_utc(local_date, local_time, zone_name)
    if at < slot:
        return SlotState.WAITING, local_date
    if at > slot + timedelta(hours=2):
        return SlotState.MISSED, local_date
    return SlotState.DUE, local_date


def in_quiet(local: time, start: time | None, end: time | None) -> bool:
    if start is None or end is None or start == end:
        return False
    clock = local.replace(second=0, microsecond=0)
    if start < end:
        return start <= clock < end
    return clock >= start or clock < end


def materiality_worsened(previous: Decimal, current: Decimal) -> bool:
    if previous <= 0:
        return current > previous
    return current >= money(previous * Decimal("1.20"))


def content_hash(metrics: dict) -> str:
    import hashlib

    raw = json.dumps(metrics, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def escape_html(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def split_parts(blocks: list[str], limit: int = PART_LIMIT) -> list[str]:
    parts: list[str] = []
    current = ""
    for block in blocks:
        for piece in _chunks(block, limit):
            candidate = piece if not current else f"{current}\n\n{piece}"
            if len(candidate) <= limit:
                current = candidate
                continue
            if current:
                parts.append(current)
            current = piece
    if current:
        parts.append(current)
    return parts


def _chunks(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    rest = text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = rest.rfind(" ", 0, limit)
        if cut < limit // 2:
            cut = _safe_cut(rest, limit)
        chunks.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        chunks.append(rest)
    return chunks


def _safe_cut(text: str, limit: int) -> int:
    cut = limit
    amp = text.rfind("&", 0, cut)
    if amp < 0:
        return cut
    semi = text.find(";", amp)
    if semi < 0 or semi >= cut:
        return max(amp, 1)
    return cut


def _wall_exists(naive: datetime, zone: ZoneInfo) -> bool:
    aware = naive.replace(tzinfo=zone)
    back = aware.astimezone(UTC_ZONE).astimezone(zone).replace(tzinfo=None)
    return back == naive


UTC_ZONE = ZoneInfo("UTC")
