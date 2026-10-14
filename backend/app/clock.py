from contextvars import ContextVar, Token
from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    def __init__(self, moment: datetime) -> None:
        if moment.tzinfo is None:
            raise ValueError("часы должны быть с временной зоной")
        self.moment = moment

    def now(self) -> datetime:
        return self.moment


_clock: ContextVar[Clock | None] = ContextVar("clock", default=None)


def set_clock(clock: Clock) -> Token[Clock | None]:
    return _clock.set(clock)


def reset_clock(token: Token[Clock | None]) -> None:
    _clock.reset(token)


def now() -> datetime:
    clock = _clock.get()
    if clock is None:
        return SystemClock().now()
    return clock.now()
