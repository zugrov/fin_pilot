from dataclasses import dataclass
from datetime import date
from decimal import Decimal

CASH_COLUMNS = (
    "external_id",
    "wallet_code",
    "business_date",
    "direction",
    "amount",
    "currency",
    "counterparty_inn",
    "counterparty_name",
    "description",
    "document_number",
    "category_code",
    "direction_code",
)

CLIENTBANK_VERSION = "1.03"
KNOWN_FORMATS = {"csv", "xlsx", "clientbank"}
KNOWN_ENCODINGS = {"utf-8", "utf-8-sig", "cp1251"}


class ImportFormatError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class ImportLine:
    row_number: int
    external_id: str
    wallet_code: str
    business_date: date | None
    direction: str
    amount: Decimal | None
    currency: str
    counterparty_inn: str
    counterparty_name: str
    description: str
    document_number: str
    category_code: str
    direction_code: str
    errors: tuple[str, ...]
    raw: dict[str, str]

    def canonical(self) -> dict[str, str]:
        moment = "" if self.business_date is None else self.business_date.isoformat()
        amount = "" if self.amount is None else format(self.amount, "f")
        return {
            "external_id": self.external_id,
            "wallet_code": self.wallet_code,
            "business_date": moment,
            "direction": self.direction,
            "amount": amount,
            "currency": self.currency,
            "counterparty_inn": self.counterparty_inn,
            "counterparty_name": self.counterparty_name,
            "description": self.description,
            "document_number": self.document_number,
            "category_code": self.category_code,
            "direction_code": self.direction_code,
        }
