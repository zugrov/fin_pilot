#!/usr/bin/env python3
# ruff: noqa: E402
"""Hold-out: строки карточки 51 (август) × секции ОДДС в demo-БД (локальный audit).

Не product-код. Без вывода названий контрагентов и текстов назначений.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import psycopg
from app.domain.imports.fa_r03.cash_flow_sections import section_for_account
from app.domain.imports.fa_r03.xls_reader import read_card51
from app.domain.money import money

YEAR = 2026
MONTH = 8

_LOCAL_DB_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def _assert_localhost_database(url: str) -> None:
    """Запрет подключения к удалённым БД (в т.ч. staging/prod)."""
    normalized = url.replace("postgresql+psycopg://", "postgresql://", 1)
    host = (urlparse(normalized).hostname or "").strip().lower()
    if host not in _LOCAL_DB_HOSTS:
        print(
            "error: database-url must be localhost only (127.0.0.1, localhost, ::1)",
            file=sys.stderr,
        )
        raise SystemExit(3)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Сверка секций ОДДС: карточка 51 × cash в БД")
    parser.add_argument("--card-xls", required=True, type=Path, help="Путь к .xls карточки 51")
    parser.add_argument("--database-url", required=True, help="PostgreSQL URL (demo-БД)")
    parser.add_argument("--company-id", required=True, type=uuid.UUID, help="UUID компании в БД")
    return parser.parse_args()


def _product_section(conn: psycopg.Connection, company_id: uuid.UUID) -> dict[tuple, str]:
    """Ключ (date, direction, amount) → секция продукта (или unmapped)."""
    sql = """
        SELECT ct.business_date, ct.direction, ct.amount,
               COALESCE(cc.cash_flow_section, 'unmapped') AS section
        FROM cash_transactions ct
        LEFT JOIN cash_categories cc ON cc.id = ct.category_id
        WHERE ct.company_id = %s
          AND ct.business_date >= %s AND ct.business_date < %s
          AND ct.status = 'posted'
    """
    start = f"{YEAR}-{MONTH:02d}-01"
    end = f"{YEAR}-{MONTH + 1:02d}-01" if MONTH < 12 else f"{YEAR + 1}-01-01"
    rows: dict[tuple, str] = {}
    with conn.cursor() as cur:
        cur.execute(sql, (company_id, start, end))
        for business_date, direction, amount, section in cur.fetchall():
            key = (business_date.isoformat(), direction, money(amount))
            rows[key] = section
    return rows


def main() -> int:
    args = _parse_args()
    _assert_localhost_database(args.database_url)
    if not args.card_xls.is_file():
        print("error: card-xls not found", file=sys.stderr)
        return 2

    sheet = read_card51(args.card_xls)
    card_rows = [
        row
        for row in sheet.rows
        if row.business_date.year == YEAR and row.business_date.month == MONTH
    ]

    with psycopg.connect(args.database_url) as conn:
        by_key = _product_section(conn, args.company_id)

    matched = 0
    unmapped_operating = 0
    mismatches = 0
    unmatched_card = 0
    gap_samples: list[str] = []

    for row in card_rows:
        direction = row.direction
        amount = money(row.debit_amount if direction == "in" else row.credit_amount)
        expected = section_for_account(row.counter_account, direction) or "unknown"
        key = (row.business_date.isoformat(), direction, amount)
        product = by_key.get(key)
        if product is None:
            unmatched_card += 1
            continue
        if expected == product:
            matched += 1
        elif product == "unmapped" and expected == "operating":
            unmapped_operating += 1
            if len(gap_samples) < 10:
                gap_samples.append(
                    f"{key[0]} {direction} {amount} corr={row.counter_account} "
                    "expected=operating product=unmapped"
                )
        else:
            mismatches += 1

    total = len(card_rows)
    print(f"card51_rows={total}")
    print(f"section_match_rows={matched}")
    print(f"product_unmapped_operating={unmapped_operating}")
    print(f"other_mismatch={mismatches}")
    print(f"card_row_no_cash_match={unmatched_card}")
    for line in gap_samples:
        print(f"gap_sample: {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
