"""P1a: общий справочник версий норм — чтение только для сессии."""

from decimal import Decimal

from sqlalchemy import text
from tests.integration.conftest import login, open_workspace, register_and_verify

NORM_2026_ID = "a0000000-0000-4000-8000-000000000001"
FNS_2026_SOURCE = "https://www.nalog.gov.ru/rn95/taxation/taxes/nds_usn/"


def _auth(client, admin, email: str) -> None:
    register_and_verify(client, admin, email)
    login(client, email)
    open_workspace(client)


def test_tax_norms_current_requires_session(client, admin) -> None:
    response = client.get("/api/v1/tax-norms/current", params={"as_of": "2026-06-01"})
    assert response.status_code == 401


def test_tax_norms_before_2026_not_found(client, admin) -> None:
    _auth(client, admin, "norms2025@example.com")
    response = client.get("/api/v1/tax-norms/current", params={"as_of": "2025-12-31"})
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_tax_norms_current_2026_matches_adr_caps(client, admin) -> None:
    _auth(client, admin, "norms2026@example.com")

    response = client.get("/api/v1/tax-norms/current", params={"as_of": "2026-12-31"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "confirmed"
    assert body["needs_review_banner"] is False
    assert body["verified_by"] == "editorial"
    assert body["source_url"] == FNS_2026_SOURCE
    assert "сверено редакцией по ссылкам выше" in body["notes"]
    assert "2026_0204_UsnNds.pdf" in body["notes"]
    values = body["values"]
    assert values["usn_vat_exemption_threshold_rub"] == "20000000.00"
    assert values["computed_special_cap_5_rub"] == "272500000.00"
    assert values["computed_special_cap_7_rub"] == "490500000.00"
    assert values["special_rates_deflator"] == "1.090000"
    assert values["vat_rates_general_percent"] == ["22", "10", "0"]
    assert values["vat_rates_special_percent"] == ["5", "7"]
    labels = {x["label"] for x in values["vat_calculated_rates"]}
    assert labels == {"22/122", "10/110", "5/105", "7/107"}
    frac_22 = next(x for x in values["vat_calculated_rates"] if x["label"] == "22/122")
    assert frac_22["numerator"] == "22"
    assert frac_22["denominator"] == "122"
    assert frac_22["fraction"] == "0.18032787"

    dec31 = client.get("/api/v1/tax-norms/current", params={"as_of": "2026-12-31"})
    jan1 = client.get("/api/v1/tax-norms/current", params={"as_of": "2027-01-01"})
    assert dec31.status_code == 200
    assert jan1.status_code == 200
    assert dec31.json()["id"] != jan1.json()["id"]
    assert jan1.json()["status"] == "needs_review"
    assert jan1.json()["needs_review_banner"] is True
    assert jan1.json()["values"]["usn_vat_exemption_threshold_rub"] is None


def test_tax_norms_deflator_precision_via_api(client, admin) -> None:
    _auth(client, admin, "normsdefl@example.com")
    with admin.begin() as connection:
        connection.execute(
            text(
                "UPDATE tax_norm_versions SET special_rates_deflator = 1.093000 "
                "WHERE id = :id"
            ),
            {"id": NORM_2026_ID},
        )
    response = client.get("/api/v1/tax-norms/current", params={"as_of": "2026-06-01"})
    assert response.status_code == 200
    values = response.json()["values"]
    assert values["special_rates_deflator"] == "1.093000"
    assert values["computed_special_cap_5_rub"] == "273250000.00"
    assert values["computed_special_cap_7_rub"] == "491850000.00"
    with admin.begin() as connection:
        connection.execute(
            text(
                "UPDATE tax_norm_versions SET special_rates_deflator = 1.090000 "
                "WHERE id = :id"
            ),
            {"id": NORM_2026_ID},
        )


def test_tax_norms_seed_periods_do_not_overlap(admin) -> None:
    """Дублирует гарантию EXCLUDE (btree_gist) для seed после TRUNCATE."""
    with admin.connect() as connection:
        overlap = connection.execute(
            text(
                """
                SELECT COUNT(*) FROM tax_norm_versions a
                JOIN tax_norm_versions b ON a.id < b.id
                WHERE daterange(
                        a.valid_from,
                        COALESCE(a.valid_to, 'infinity'::date),
                        '[]'
                      )
                  && daterange(
                        b.valid_from,
                        COALESCE(b.valid_to, 'infinity'::date),
                        '[]'
                      )
                """
            )
        ).scalar_one()
    assert overlap == 0


def test_tax_norms_no_write_methods(client, admin) -> None:
    _auth(client, admin, "normswrite@example.com")
    post = client.post("/api/v1/tax-norms/current", params={"as_of": "2026-06-01"})
    assert post.status_code == 405


def test_vat_rate_fraction_rounding_rule() -> None:
    """22/122 → 0.18032787 при 8 знаках, ROUND_HALF_UP (как money)."""
    from app.domain.money import vat_rate_fraction, vat_rate_fraction_str

    value = vat_rate_fraction(Decimal("22") / Decimal("122"))
    assert vat_rate_fraction_str(value) == "0.18032787"
