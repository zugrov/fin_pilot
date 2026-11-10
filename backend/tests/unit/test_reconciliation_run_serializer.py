from app.services.reconciliation_run_service import _scrub_json


def test_scrub_json_removes_pii_keys() -> None:
    raw = {
        "matched": 1,
        "purpose": "secret",
        "nested": {"counterparty": "X", "amount": "100.00"},
        "group": [{"payee": "Y", "id": "g1"}],
    }
    cleaned = _scrub_json(raw)
    assert "purpose" not in cleaned
    assert cleaned["matched"] == 1
    assert "counterparty" not in cleaned["nested"]
    assert cleaned["nested"]["amount"] == "100.00"
    assert "payee" not in cleaned["group"][0]
    assert cleaned["group"][0]["id"] == "g1"
