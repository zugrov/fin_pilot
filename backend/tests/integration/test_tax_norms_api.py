"""P1a: общий справочник версий норм — чтение только для сессии."""

from decimal import Decimal

from schema_sql import iter_statements
from sqlalchemy import text
from tests.integration.conftest import (
    _TAX_NORM_VERSIONS_SEED_SQL,
    BACKEND,
    login,
    open_workspace,
    register_and_verify,
)

NORM_2026_ID = "a0000000-0000-4000-8000-000000000001"
NORM_2027_ID = "a0000000-0000-4000-8000-000000000003"
NORM_2028_PARTIAL_ID = "a0000000-0000-4000-8000-000000000005"
NORM_2030_DRAFT_ID = "a0000000-0000-4000-8000-000000000004"
FNS_2026_SOURCE = "https://www.nalog.gov.ru/rn95/taxation/taxes/nds_usn/"
PRAVO_2027_DEFLATOR_SOURCE = "http://publication.pravo.gov.ru/document/0001202610300013"
FNS_2028_SOURCE = "https://www.nalog.gov.ru/rn11/news/activities_fts/16668026/"
EXPECTED_NORM_ROW_IDS = frozenset(
    {NORM_2026_ID, NORM_2027_ID, NORM_2028_PARTIAL_ID, NORM_2030_DRAFT_ID}
)

_TAX_NORM_ROW_SELECT = text(
    """
    SELECT
      id::text,
      valid_from::text,
      valid_to::text,
      status,
      source_url,
      verified_at AT TIME ZONE 'UTC' AS verified_at_utc,
      verified_by,
      notes,
      usn_vat_exemption_threshold_rub::text,
      special_rate_base_5_cap_base_rub::text,
      special_rate_base_7_cap_base_rub::text,
      special_rates_deflator::text,
      vat_rates_general::text,
      vat_rates_special::text
    FROM tax_norm_versions
    ORDER BY valid_from, id
    """
)


def _auth(client, admin, email: str) -> None:
    register_and_verify(client, admin, email)
    login(client, email)
    open_workspace(client)


def _tax_norm_rows(connection) -> list[dict]:
    rows = connection.execute(_TAX_NORM_ROW_SELECT).mappings().all()
    result: list[dict] = []
    for row in rows:
        item = dict(row)
        ts = item.pop("verified_at_utc")
        item["verified_at"] = ts.isoformat().replace("+00:00", "Z")
        result.append(item)
    return result


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


def test_tax_norms_2027_confirmed(client, admin) -> None:
    _auth(client, admin, "norms2027@example.com")
    response = client.get("/api/v1/tax-norms/current", params={"as_of": "2027-06-01"})
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == NORM_2027_ID
    assert body["status"] == "confirmed"
    assert body["needs_review_banner"] is False
    assert body["source_url"] == PRAVO_2027_DEFLATOR_SOURCE
    assert body["verified_by"] == "editorial"
    assert "414502711" in body["notes"]
    values = body["values"]
    assert values["usn_vat_exemption_threshold_rub"] == "20000000.00"
    assert values["computed_special_cap_5_rub"] == "288250000.00"
    assert values["computed_special_cap_7_rub"] == "518850000.00"
    assert values["special_rates_deflator"] == "1.153000"
    assert values["vat_rates_general_percent"] == ["22", "10", "0"]
    assert values["vat_rates_special_percent"] == ["5", "7"]


def test_tax_norms_2028_partially_confirmed(client, admin) -> None:
    _auth(client, admin, "norms2028@example.com")
    response = client.get("/api/v1/tax-norms/current", params={"as_of": "2028-06-01"})
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == NORM_2028_PARTIAL_ID
    assert body["status"] == "partially_confirmed"
    assert body["needs_review_banner"] is True
    assert body["source_url"] == FNS_2028_SOURCE
    values = body["values"]
    assert values["usn_vat_exemption_threshold_rub"] == "20000000.00"
    assert values["computed_special_cap_5_rub"] is None
    assert values["computed_special_cap_7_rub"] is None
    assert values["special_rates_deflator"] is None
    assert "дефлятор 2028" in body["notes"].lower() or "2028 и 2029" in body["notes"]


def test_tax_norms_2029_vs_2030_versions(client, admin) -> None:
    _auth(client, admin, "norms2030@example.com")
    y2029 = client.get("/api/v1/tax-norms/current", params={"as_of": "2029-12-31"})
    y2030 = client.get("/api/v1/tax-norms/current", params={"as_of": "2030-01-01"})
    assert y2029.status_code == 200
    assert y2030.status_code == 200
    assert y2029.json()["id"] == NORM_2028_PARTIAL_ID
    assert y2030.json()["id"] == NORM_2030_DRAFT_ID
    assert y2030.json()["status"] == "needs_review"
    assert y2030.json()["needs_review_banner"] is True
    assert y2030.json()["values"]["usn_vat_exemption_threshold_rub"] is None


def test_tax_norms_seed_row_ids(admin) -> None:
    with admin.connect() as connection:
        rows = connection.execute(
            text("SELECT id::text FROM tax_norm_versions ORDER BY valid_from")
        ).scalars().all()
    assert set(rows) == EXPECTED_NORM_ROW_IDS


def test_tax_norm_versions_migrated_rows_match_seed_fixture(migrated_database) -> None:
    """Снимок после 0018+0019 совпадает с tax_norm_versions_seed.sql."""
    path_0018 = BACKEND / "alembic/sql/0018_tax_norm_versions.sql"
    path_0019 = BACKEND / "alembic/sql/0019_tax_norms_threshold_2027.sql"
    with migrated_database.begin() as connection:
        connection.execute(text("TRUNCATE tax_norm_versions"))
        for statement in iter_statements(path_0018.read_text(encoding="utf-8")):
            if statement.lstrip().upper().startswith("INSERT"):
                connection.execute(text(statement))
        for statement in iter_statements(path_0019.read_text(encoding="utf-8")):
            connection.execute(text(statement))
        migrated = _tax_norm_rows(connection)

        connection.execute(text("TRUNCATE tax_norm_versions"))
        for statement in iter_statements(_TAX_NORM_VERSIONS_SEED_SQL):
            connection.execute(text(statement))
        seeded = _tax_norm_rows(connection)
    assert migrated == seeded


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
