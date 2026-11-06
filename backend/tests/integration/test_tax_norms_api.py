"""P1a: общий справочник версий норм — чтение только для сессии."""

from datetime import date
from decimal import Decimal

from tests.integration.conftest import PASSWORD, login, open_workspace, register_and_verify


def test_tax_norms_current_requires_session(client, admin) -> None:
    response = client.get("/api/v1/tax-norms/current", params={"as_of": "2026-06-01"})
    assert response.status_code == 401


def test_tax_norms_current_2026_matches_adr_caps(client, admin) -> None:
    register_and_verify(client, admin, "norms2026@example.com")
    login(client, "norms2026@example.com")
    open_workspace(client)

    response = client.get("/api/v1/tax-norms/current", params={"as_of": "2026-12-31"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["needs_review_banner"] is False
    values = body["values"]
    assert values["usn_vat_exemption_threshold_rub"] == "20000000.00"
    assert values["computed_special_cap_5_rub"] == "272500000.00"
    assert values["computed_special_cap_7_rub"] == "490500000.00"
    assert values["special_rates_deflator"] == "1.09"
    assert values["vat_rates_general_percent"] == ["22", "10", "0"]
    assert values["vat_rates_special_percent"] == ["5", "7"]
    labels = {x["label"] for x in values["vat_calculated_rates"]}
    assert labels == {"22/122", "10/110", "5/105", "7/107"}

    dec31 = client.get("/api/v1/tax-norms/current", params={"as_of": "2026-12-31"})
    jan1 = client.get("/api/v1/tax-norms/current", params={"as_of": "2027-01-01"})
    assert dec31.status_code == 200
    assert jan1.status_code == 200
    assert dec31.json()["id"] != jan1.json()["id"]
    assert jan1.json()["status"] == "needs_review"
    assert jan1.json()["needs_review_banner"] is True
    assert jan1.json()["values"]["usn_vat_exemption_threshold_rub"] is None


def test_tax_norms_no_write_methods(client, admin) -> None:
    register_and_verify(client, admin, "normswrite@example.com")
    login(client, "normswrite@example.com")
    open_workspace(client)

    post = client.post("/api/v1/tax-norms/current", params={"as_of": "2026-06-01"})
    assert post.status_code == 405


def test_tax_norms_model_decimal_fractions() -> None:
    """Согласованность 250×1.09 и 450×1.09 с ADR-003 (Decimal)."""
    base5 = Decimal("250000000")
    base7 = Decimal("450000000")
    d = Decimal("1.09")
    assert base5 * d == Decimal("272500000.0")
    assert base7 * d == Decimal("490500000.0")
