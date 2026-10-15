from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from app.services.billing_service import _mode_problem, _verification_problem


def _remote(test: bool | None, invoice_id: str, tenant_id: str) -> dict:
    return {
        "test": test,
        "amount": {"value": "2500.00", "currency": "RUB"},
        "shop_id": "shop-test",
        "metadata": {
            "invoice_id": invoice_id,
            "tenant_id": tenant_id,
            "interval": "month",
        },
    }


def test_test_mode_rejects_live_payment() -> None:
    settings = SimpleNamespace(billing_mode="test", yookassa_shop_id="shop-test")
    tenant = SimpleNamespace(is_live=False)
    invoice_id = uuid4()
    tenant_id = uuid4()
    invoice = SimpleNamespace(
        payable_amount=Decimal("2500.00"),
        id=invoice_id,
        tenant_id=tenant_id,
        billing_interval="month",
    )
    remote = _remote(False, str(invoice_id), str(tenant_id))
    assert _mode_problem(remote, settings, tenant) == "live_payment_test_mode"
    assert _verification_problem(remote, invoice, settings, tenant) == "live_payment_test_mode"
    missing = _remote(None, str(invoice_id), str(tenant_id))
    assert _verification_problem(missing, invoice, settings, tenant) == "live_payment_test_mode"
    accepted = _remote(True, str(invoice_id), str(tenant_id))
    assert _verification_problem(accepted, invoice, settings, tenant) is None


def test_live_mode_still_rejects_test_payment() -> None:
    settings = SimpleNamespace(billing_mode="live", yookassa_shop_id="shop-test")
    tenant = SimpleNamespace(is_live=False)
    assert _mode_problem({"test": True}, settings, tenant) == "test_payment_live_tenant"
    assert _mode_problem({"test": False}, settings, tenant) is None
