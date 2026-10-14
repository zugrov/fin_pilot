from pathlib import Path


def test_billing_domain_does_not_use_float() -> None:
    root = Path(__file__).resolve().parents[2] / "app" / "domain"
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "float(" in text or " math." in text:
            offenders.append(str(path))
    assert offenders == []
