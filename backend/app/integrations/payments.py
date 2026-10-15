from decimal import Decimal
from typing import Protocol
from uuid import uuid4

from app.config import Settings
from app.errors import AppError


class PaymentProvider(Protocol):
    def create_payment(self, idempotence_key: str, body: dict) -> dict: ...

    def get_payment(self, payment_id: str) -> dict: ...


class DisabledPaymentProvider:
    """Интеграция выключена. Успешный платёж не подделывается."""

    def create_payment(self, idempotence_key: str, body: dict) -> dict:
        raise AppError(503, "billing_integration_disabled", "Платёжная интеграция выключена")

    def get_payment(self, payment_id: str) -> dict:
        raise AppError(503, "billing_integration_disabled", "Платёжная интеграция выключена")


class YooKassaClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.send_live_payments:
            raise RuntimeError("живой платёж выключен")
        if not settings.yookassa_shop_id or not settings.yookassa_secret_key:
            raise RuntimeError("нет учётных данных ЮKassa")
        import httpx

        self.shop_id = settings.yookassa_shop_id
        self._client = httpx.Client(
            base_url=settings.yookassa_api_base,
            auth=(settings.yookassa_shop_id, settings.yookassa_secret_key),
            timeout=20.0,
        )

    def create_payment(self, idempotence_key: str, body: dict) -> dict:
        response = self._client.post(
            "/payments",
            json=body,
            headers={"Idempotence-Key": idempotence_key},
        )
        response.raise_for_status()
        payload = response.json()
        payload["shop_id"] = self.shop_id
        return payload

    def get_payment(self, payment_id: str) -> dict:
        response = self._client.get(f"/payments/{payment_id}")
        response.raise_for_status()
        payload = response.json()
        payload["shop_id"] = self.shop_id
        return payload


class FakeYooKassa:
    """Только для тестов. Фабрика приложения этот класс не возвращает."""

    def __init__(self, shop_id: str = "shop-test") -> None:
        self.shop_id = shop_id
        self.by_key: dict[str, dict] = {}
        self.by_id: dict[str, dict] = {}
        self.timeout_once = False
        self.next_test = True
        self.calls = 0

    def create_payment(self, idempotence_key: str, body: dict) -> dict:
        self.calls += 1
        existing = self.by_key.get(idempotence_key)
        if existing is not None:
            if existing["body"] != body:
                raise AppError(409, "idempotency_conflict", "Другой payload для того же ключа")
            if self.timeout_once:
                self.timeout_once = False
                raise TimeoutError("provider timeout")
            return existing["payment"]
        payment_id = str(uuid4())
        payment = {
            "id": payment_id,
            "status": "pending",
            "paid": False,
            "test": self.next_test,
            "amount": body["amount"],
            "metadata": body.get("metadata", {}),
            "confirmation": {
                "type": "redirect",
                "confirmation_url": f"https://yookassa.test/pay/{payment_id}",
            },
            "shop_id": self.shop_id,
        }
        self.by_key[idempotence_key] = {"body": body, "payment": payment}
        self.by_id[payment_id] = payment
        if self.timeout_once:
            self.timeout_once = False
            raise TimeoutError("provider timeout")
        return payment

    def get_payment(self, payment_id: str) -> dict:
        payment = self.by_id.get(payment_id)
        if payment is None:
            raise AppError(404, "not_found", "Платёж не найден у провайдера")
        return payment

    def mark(self, payment_id: str, status: str, **overrides: object) -> dict:
        payment = self.get_payment(payment_id)
        payment.update(overrides)
        payment["status"] = status
        payment["paid"] = status == "succeeded"
        return payment


def build_payment_provider(settings: Settings) -> PaymentProvider:
    if (
        settings.send_live_payments
        and settings.yookassa_shop_id
        and settings.yookassa_secret_key
    ):
        return YooKassaClient(settings)
    return DisabledPaymentProvider()


def amount_of(remote: dict) -> Decimal:
    return Decimal(str(remote["amount"]["value"]))
