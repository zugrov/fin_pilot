"""Запись CSV/ClientBank из профилей в каталог fixtures."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tests.synthetic_polygon.constants import (
    PERIOD_FROM,
    PERIOD_TO,
    POLYGON_FROZEN_ISO,
    POLYGON_RANDOM_SEED,
)
from tests.synthetic_polygon.profiles import ALL_PROFILES, CompanyProfile

REPO_FIXTURES = (
    Path(__file__).resolve().parents[1] / "fixtures" / "synthetic_polygon"
)

CASH_HEADER = (
    "external_id,wallet_code,business_date,direction,amount,currency,"
    "counterparty_inn,counterparty_name,description,document_number,category_code,direction_code\n"
)
REVENUE_HEADER = (
    "external_id,recognition_date,document_number,counterparty_inn,"
    "amount_ex_vat,vat_amount,amount_inc_vat,entry_type,direction_code\n"
)
PLAN_HEADER = (
    "external_id,direction,amount,currency,due_date,expected_date,"
    "category_code,counterparty_inn,confidence,priority,wallet_code\n"
)
BUDGET_HEADER = (
    "year,month,basis,metric_type,category_code,direction_code,amount,distribution_method\n"
)
BAL_HEADER = "wallet_code,as_of,balance,currency\n"


def _cash_csv(profile: CompanyProfile) -> str:
    lines = [CASH_HEADER]
    for row in profile.cash:
        lines.append(
            f"{row.external_id},{row.wallet_code},{row.business_date},{row.direction},"
            f"{row.amount},RUB,{row.counterparty_inn},{row.counterparty_name},"
            f"{row.description},{row.document_number},{row.category_code},\n"
        )
    return "".join(lines)


def _revenue_csv(profile: CompanyProfile) -> str:
    lines = [REVENUE_HEADER]
    for row in profile.revenue:
        lines.append(
            f"{row.external_id},{row.recognition_date},{row.document_number},"
            f"{row.counterparty_inn},{row.amount_ex_vat},{row.vat_amount},"
            f"{row.amount_inc_vat},{row.entry_type},\n"
        )
    return "".join(lines)


def _plan_csv(profile: CompanyProfile) -> str:
    if not profile.plan:
        return PLAN_HEADER
    lines = [PLAN_HEADER]
    for row in profile.plan:
        lines.append(
            f"{row.external_id},{row.direction},{row.amount},RUB,"
            f"{row.due_date},{row.expected_date},{row.category_code},,"
            f"{row.confidence},{row.priority},{row.wallet_code}\n"
        )
    return "".join(lines)


def _budget_csv(profile: CompanyProfile) -> str:
    if not profile.budget:
        return BUDGET_HEADER
    lines = [BUDGET_HEADER]
    for row in profile.budget:
        lines.append(
            f"{row.year},{row.month},{row.basis},{row.metric_type},"
            f"{row.category_code},{row.direction_code},{row.amount},"
            f"{row.distribution_method}\n"
        )
    return "".join(lines)


def _balances_csv(profile: CompanyProfile) -> str:
    lines = [BAL_HEADER]
    for row in profile.balances:
        lines.append(f"{row.wallet_code},{row.as_of},{row.balance},{row.currency}\n")
    return "".join(lines)


def _clientbank_txt(profile: CompanyProfile) -> str:
    if not profile.clientbank:
        return ""

    def ru_date(iso: str) -> str:
        y, m, d = iso.split("-")
        return f"{d}.{m}.{y}"

    parts = [
        "1CClientBankExchange",
        "ВерсияФормата=1.03",
        "Кодировка=UTF-8",
        f"ДатаКонца={ru_date(PERIOD_TO)}",
    ]
    for doc in profile.clientbank:
        parts.extend(
            [
                "СекцияДокумент=Платежное поручение",
                f"Номер={doc.number}",
                f"Дата={doc.date}",
                f"Сумма={doc.amount}",
                f"Плательщик={doc.payer_name}",
                f"ПлательщикИНН={doc.payer_inn}",
                f"Получатель={doc.payee_name}",
                f"ПолучательИНН={doc.payee_inn}",
                f"НазначениеПлатежа={doc.purpose}",
                f"{doc.posted_field}={doc.posted_date}",
                "КонецДокумента",
            ]
        )
    parts.append("КонецФайла")
    return "\n".join(parts) + "\n"


def write_profile_fixtures(profile: CompanyProfile, root: Path = REPO_FIXTURES) -> dict[str, str]:
    folder = root / profile.slug
    folder.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    mapping = {
        "cash.csv": _cash_csv(profile),
        "revenue.csv": _revenue_csv(profile),
        "planned_cash.csv": _plan_csv(profile),
        "budget.csv": _budget_csv(profile),
        "balances.csv": _balances_csv(profile),
    }
    cb = _clientbank_txt(profile)
    if cb:
        mapping["clientbank.txt"] = cb
    for name, body in mapping.items():
        path = folder / name
        path.write_text(body, encoding="utf-8")
        files[name] = hashlib.sha256(body.encode("utf-8")).hexdigest()
    meta = {
        "slug": profile.slug,
        "display_name": profile.display_name,
        "industry_label": profile.industry_label,
        "tax": profile.tax.__dict__,
        "files_sha256": files,
    }
    (folder / "profile.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return files


def write_polygon_oracle_json(repo_root: Path) -> None:
    from tests.synthetic_polygon.constants import (
        PERIOD_FROM,
        PERIOD_TO,
        POLYGON_FROZEN_ISO,
        POLYGON_RANDOM_SEED,
    )
    from tests.synthetic_polygon.expectations import (
        GROUP_CASH_ORACLE,
        GROUP_REVENUE_ORACLE,
        ORACLE,
        SERVICES_PLAN_MOVE,
    )

    payload = {
        "polygon_random_seed": POLYGON_RANDOM_SEED,
        "polygon_frozen_iso": POLYGON_FROZEN_ISO,
        "period_from": PERIOD_FROM,
        "period_to": PERIOD_TO,
        "revenue_label": "Выручка без НДС",
        "group": {"cash_total": GROUP_CASH_ORACLE, "revenue": GROUP_REVENUE_ORACLE},
        "companies": {
            slug: {
                "opening_balance": exp.opening_balance,
                "cash_in": exp.cash_in,
                "cash_out": exp.cash_out,
                "net_cash_flow": exp.net_cash_flow,
                "cash_total": exp.cash_total,
                "operation_count": exp.operation_count,
                "revenue_net_ex_vat": exp.revenue_net_ex_vat,
            }
            for slug, exp in ORACLE.items()
        },
        "plan_move_services": {
            "amount": SERVICES_PLAN_MOVE.amount,
            "cash_total_unchanged": SERVICES_PLAN_MOVE.cash_total_unchanged,
            "forecast_unpaid_before": (
                f"Неоплаченная выплата {SERVICES_PLAN_MOVE.amount} "
                f"на {SERVICES_PLAN_MOVE.forecast_contribution_date_before}"
            ),
            "forecast_unpaid_after": (
                f"Неоплаченная выплата {SERVICES_PLAN_MOVE.amount} "
                f"на {SERVICES_PLAN_MOVE.forecast_contribution_date_after}"
            ),
            "calendar_expected_after": SERVICES_PLAN_MOVE.moved_expected,
            "moved_expected": SERVICES_PLAN_MOVE.moved_expected,
            "plan_marker_due": SERVICES_PLAN_MOVE.due_date,
        },
    }
    out = repo_root / "frontend" / "e2e" / "fixtures" / "polygon-oracle.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_all(root: Path = REPO_FIXTURES) -> dict:
    manifest: dict = {
        "polygon_random_seed": POLYGON_RANDOM_SEED,
        "polygon_frozen_iso": POLYGON_FROZEN_ISO,
        "period_from": PERIOD_FROM,
        "period_to": PERIOD_TO,
        "profiles": {},
    }
    for profile in ALL_PROFILES:
        manifest["profiles"][profile.slug] = write_profile_fixtures(profile, root)
    (root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
