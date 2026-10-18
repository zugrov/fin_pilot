"""Read-only SQL-проверки для browser E2E (только finpilot_test)."""

from __future__ import annotations

import argparse
import json
import sys
import uuid

from sqlalchemy import create_engine, text
from tests.e2e.env import apply_e2e_env, assert_finpilot_test_only


def _engine():
    port = apply_e2e_env()
    assert_finpilot_test_only(port)
    return create_engine(f"postgresql+psycopg://127.0.0.1:{port}/finpilot_test")


def revenue_count(company_id: str, document_number: str | None) -> int:
    cid = uuid.UUID(company_id)
    with _engine().connect() as conn:
        if document_number is None:
            row = conn.execute(
                text(
                    "SELECT count(*) FROM revenue_entries "
                    "WHERE company_id = :cid AND status <> 'void'"
                ),
                {"cid": cid},
            ).scalar_one()
        else:
            row = conn.execute(
                text(
                    "SELECT count(*) FROM revenue_entries "
                    "WHERE company_id = :cid AND document_number = :doc AND status <> 'void'"
                ),
                {"cid": cid, "doc": document_number},
            ).scalar_one()
    return int(row)


def revenue_entry_id(company_id: str, document_number: str) -> str | None:
    cid = uuid.UUID(company_id)
    with _engine().connect() as conn:
        value = conn.execute(
            text(
                "SELECT id FROM revenue_entries "
                "WHERE company_id = :cid AND document_number = :doc AND status <> 'void' "
                "ORDER BY created_at LIMIT 1"
            ),
            {"cid": cid, "doc": document_number},
        ).scalar_one_or_none()
    return str(value) if value is not None else None


def audit_count_for_entity(action: str, entity_id: str) -> int:
    eid = uuid.UUID(entity_id)
    with _engine().connect() as conn:
        row = conn.execute(
            text(
                "SELECT count(*) FROM audit_log "
                "WHERE action = :action AND entity_id = :eid"
            ),
            {"action": action, "eid": eid},
        ).scalar_one()
    return int(row)


def match_count_for_revenue(revenue_entry_id: str) -> int:
    rid = uuid.UUID(revenue_entry_id)
    with _engine().connect() as conn:
        row = conn.execute(
            text("SELECT count(*) FROM revenue_cash_matches WHERE revenue_entry_id = :rid"),
            {"rid": rid},
        ).scalar_one()
    return int(row)


def latest_match_id(revenue_entry_id: str) -> str | None:
    rid = uuid.UUID(revenue_entry_id)
    with _engine().connect() as conn:
        value = conn.execute(
            text(
                "SELECT id FROM revenue_cash_matches WHERE revenue_entry_id = :rid "
                "ORDER BY created_at LIMIT 1"
            ),
            {"rid": rid},
        ).scalar_one_or_none()
    return str(value) if value is not None else None


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_count = sub.add_parser("revenue-count")
    p_count.add_argument("--company-id", required=True)
    p_count.add_argument("--document-number", default=None)

    p_id = sub.add_parser("revenue-entry-id")
    p_id.add_argument("--company-id", required=True)
    p_id.add_argument("--document-number", required=True)

    p_audit = sub.add_parser("audit-count")
    p_audit.add_argument("--action", required=True)
    p_audit.add_argument("--entity-id", required=True)

    p_match = sub.add_parser("match-count")
    p_match.add_argument("--revenue-entry-id", required=True)

    p_match_id = sub.add_parser("latest-match-id")
    p_match_id.add_argument("--revenue-entry-id", required=True)

    args = parser.parse_args()
    if args.cmd == "revenue-count":
        payload = {"count": revenue_count(args.company_id, args.document_number)}
    elif args.cmd == "revenue-entry-id":
        payload = {"id": revenue_entry_id(args.company_id, args.document_number)}
    elif args.cmd == "audit-count":
        payload = {"count": audit_count_for_entity(args.action, args.entity_id)}
    elif args.cmd == "latest-match-id":
        payload = {"id": latest_match_id(args.revenue_entry_id)}
    else:
        payload = {"count": match_count_for_revenue(args.revenue_entry_id)}

    json.dump(payload, sys.stdout)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
