#!/usr/bin/env python3
"""Автоматизированная приёмка стенда по docs/runbook-staging-acceptance.md (только HTTP API).

Секреты: через окружение или getpass; в acceptance-report.md не попадают.
Зависимости: стандартная библиотека Python 3.12+.
"""

from __future__ import annotations

import csv
import getpass
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_CSV = REPO_ROOT / "fixtures" / "staging_sales_gross_only.csv"
REPORT_PATH = REPO_ROOT / "acceptance-report.md"

PERIOD_OCT = "date_from=2026-10-01&date_to=2026-10-31"
PERIOD_YTD_OCT = "date_from=2026-01-01&date_to=2026-10-31"
AS_OF_OCT = "2026-10-31"

PROFILE_DRAFT_NA = {
    "org_form": "ooo",
    "tax_system": "usn",
    "usn_tax_object": "income",
    "vat_status": "not_applicable",
    "accounting_source": "onec",
    "money_channels": ["bank"],
    "month_close_policy": "calendar_month_end",
    "revenue_recognition_method": "accrual",
    "is_new_organization": True,
    "change_reason": "staging acceptance",
}


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    if value is not None and not value.strip():
        return default
    return value


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    shown = local[:2] if len(local) > 2 else "*"
    return f"{shown}***@{domain}"


@dataclass
class StepResult:
    step: str
    expected: str
    actual: str
    ok: bool


@dataclass
class Report:
    rows: list[StepResult] = field(default_factory=list)

    def record(self, step: str, expected: str, actual: str, ok: bool) -> None:
        self.rows.append(StepResult(step, expected, actual, ok,))

    @property
    def success(self) -> bool:
        return all(row.ok for row in self.rows)


def flags_summary(flags: list[str] | None) -> str:
    if not flags:
        return "[]"
    return ",".join(sorted(flags))


def evaluate_quality_flags(
    flags: list[str] | None,
    *,
    want_unknown: bool | None,
    want_from_profile: bool | None,
) -> tuple[bool, str]:
    has_u = "vat_basis_unknown" in (flags or [])
    has_p = "vat_basis_from_profile" in (flags or [])
    parts: list[str] = []
    ok = True
    if want_unknown is not None:
        hit = has_u == want_unknown
        parts.append(f"vat_basis_unknown={has_u}")
        ok = ok and hit
    if want_from_profile is not None:
        hit = has_p == want_from_profile
        parts.append(f"vat_basis_from_profile={has_p}")
        ok = ok and hit
    return ok, "; ".join(parts)


def evaluate_metric_basis(body: dict[str, Any], expected: str | None) -> tuple[bool, str]:
    actual = str(body.get("metric_basis", ""))
    if expected is None:
        return True, actual or "(нет)"
    return actual == expected, actual


def evaluate_vat_threshold(
    body: dict[str, Any],
    *,
    present: bool,
    status: str | None = None,
) -> tuple[bool, str]:
    block = body.get("vat_threshold")
    if not present:
        ok = block is None
        return ok, "absent" if block is None else f"present status={block.get('status')}"
    if block is None:
        return False, "absent"
    actual_status = block.get("status")
    if status is not None and actual_status != status:
        return False, f"status={actual_status}"
    return True, f"status={actual_status}"


def evaluate_http_status(code: int, expected: int) -> tuple[bool, str]:
    return code == expected, str(code)


def evaluate_isolation_status(code: int) -> tuple[bool, str]:
    return code == 404, str(code)


class HttpClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._jar = CookieJar()
        self._csrf: str | None = None
        self._tenant: str | None = None
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar))

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        query: str = "",
        tenant: str | None = None,
        idempotency: str | None = None,
    ) -> tuple[int, dict[str, Any] | None, str]:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{query}" if "?" not in path else f"{self.base_url}{path}&{query}"
        data = None
        headers = {"Accept": "application/json"}
        if json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self._csrf:
            headers["X-CSRF-Token"] = self._csrf
        tid = tenant if tenant is not None else self._tenant
        if tid:
            headers["X-Tenant-Id"] = tid
        if idempotency:
            headers["Idempotency-Key"] = idempotency
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener.open(req, timeout=120) as resp:
                raw = resp.read().decode("utf-8")
                body = json.loads(raw) if raw.strip() else None
                return resp.status, body, ""
        except urllib.error.HTTPError as err:
            raw = err.read().decode("utf-8", errors="replace")
            try:
                body = json.loads(raw) if raw.strip() else None
            except json.JSONDecodeError:
                body = None
            return err.code, body, raw[:200]

    def set_csrf(self, token: str | None) -> None:
        self._csrf = token

    def set_tenant(self, tenant_id: str | None) -> None:
        self._tenant = tenant_id


def print_sql_verify_hint(email: str, postgres_exec_hint: str) -> None:
    safe_email = email.replace("'", "''")
    print("\n--- Подтверждение почты (SQL, выполнить на стенде) ---")
    print(
        postgres_exec_hint
        + f" \\\n  -c \"SELECT payload_redacted->>'link' FROM transactional_email_outbox "
        f"WHERE type = 'verify_email' AND lower(to_email) = lower('{safe_email}') "
        f"ORDER BY created_at DESC LIMIT 1;\""
    )
    print("Извлеките query-параметр token из ссылки, затем введите его ниже (не сохраняется в отчёт).\n")


def prompt_verify_token(env_name: str) -> str:
    token = _env(env_name)
    if token:
        return token.strip()
    return getpass.getpass(f"{env_name} (token, скрытый ввод): ").strip()


def load_gross_sales_csv(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for item in csv.DictReader(handle):
            rows.append(item)
    return rows


def billing_activate(client: HttpClient, company_id: str, report: Report) -> bool:
    quoted = client.request(
        "POST",
        "/api/v1/billing/quote",
        json_body={"companies": 1, "interval": "month", "payable_amount": "1.00"},
    )
    ok, actual = evaluate_http_status(quoted[0], 200)
    report.record("billing.quote", "HTTP 200", actual, ok)
    if not ok:
        return False
    qid = (quoted[1] or {}).get("id")
    checked = client.request(
        "POST",
        "/api/v1/billing/checkout",
        json_body={"quote_id": qid, "offer_accepted": True, "discount_percent": "0"},
        idempotency=secrets.token_hex(16),
    )
    ok, actual = evaluate_http_status(checked[0], 200)
    report.record("billing.checkout", "HTTP 200", actual, ok)
    webhook_id = _env("STAGING_WEBHOOK_PAYMENT_OBJECT_ID")
    if webhook_id and ok:
        wh = client.request(
            "POST",
            "/api/v1/integrations/yookassa/webhook",
            json_body={"event": "payment.succeeded", "object": {"id": webhook_id}},
        )
        ok_wh, actual_wh = evaluate_http_status(wh[0], 200)
        report.record("billing.webhook", "HTTP 200", actual_wh, ok_wh)
    activated = client.request("POST", f"/api/v1/billing/companies/{company_id}/activate")
    ok_act, actual_act = evaluate_http_status(activated[0], 200)
    report.record(
        "billing.activate",
        "HTTP 200",
        actual_act if ok_act else f"{actual_act} (нужен worker/webhook?)",
        ok_act,
    )
    return ok_act


def ensure_revenue_source(client: HttpClient, company_id: str, coverage: str) -> None:
    source = client.request(
        "POST",
        f"/api/v1/companies/{company_id}/sources",
        json_body={
            "name": "Приёмка продажи",
            "type": "file",
            "namespace": "sales",
            "format": "csv",
            "dataset": "revenue",
            "vat_basis": "unknown",
        },
    )
    if source[0] != 200:
        raise RuntimeError(f"revenue source: HTTP {source[0]}")
    sid = (source[1] or {}).get("id")
    client.request(
        "POST",
        f"/api/v1/companies/{company_id}/sources/{sid}/coverage",
        json_body={"coverage_through": coverage},
    )


def post_gross_sale(
    client: HttpClient,
    company_id: str,
    *,
    day: str,
    amount: str,
    doc: str,
    key: str | None = None,
) -> None:
    created = client.request(
        "POST",
        f"/api/v1/companies/{company_id}/revenue",
        json_body={
            "recognition_date": day,
            "document_number": doc,
            "amount_inc_vat": amount,
            "entry_type": "sale",
            "vat_basis": "unknown",
        },
        idempotency=key or uuid4().hex,
    )
    if created[0] != 200:
        raise RuntimeError(f"revenue POST: HTTP {created[0]} {created[2]}")


def post_sales_from_fixture(client: HttpClient, company_id: str) -> None:
    for row in load_gross_sales_csv(FIXTURE_CSV):
        post_gross_sale(
            client,
            company_id,
            day=row["recognition_date"],
            amount=row["amount_inc_vat"],
            doc=row["document_number"],
            key=row["external_id"],
        )


def dashboard(client: HttpClient, company_id: str, query: str = PERIOD_OCT) -> dict[str, Any] | None:
    code, body, _ = client.request("GET", f"/api/v1/companies/{company_id}/dashboard", query=query)
    if code != 200 or not isinstance(body, dict):
        return None
    return body


def receivable(client: HttpClient, company_id: str) -> dict[str, Any] | None:
    code, body, _ = client.request(
        "GET",
        f"/api/v1/companies/{company_id}/reports/receivable-aging",
        query=f"as_of={AS_OF_OCT}",
    )
    if code != 200 or not isinstance(body, dict):
        return None
    return body


def patch_profile_draft(client: HttpClient, company_id: str, **overrides: Any) -> int:
    body = {**PROFILE_DRAFT_NA, **overrides}
    code, _, _ = client.request(
        "PATCH",
        f"/api/v1/companies/{company_id}/organization-profile/draft",
        json_body=body,
    )
    return code


def confirm_profile(client: HttpClient, company_id: str) -> int:
    listed = client.request(
        "GET",
        f"/api/v1/companies/{company_id}/organization-profile/versions",
    )
    if listed[0] != 200 or not listed[1]:
        return listed[0]
    versions = listed[1].get("versions") or []
    if not versions:
        return 409
    version_id = versions[-1]["version_id"]
    confirmed = client.request(
        "POST",
        f"/api/v1/companies/{company_id}/organization-profile/versions/{version_id}/confirm",
        idempotency=uuid4().hex,
    )
    return confirmed[0]


def setup_company(
    client: HttpClient,
    tenant_id: str,
    name: str,
    report: Report,
    step_prefix: str,
) -> str | None:
    client.set_tenant(tenant_id)
    created = client.request(
        "POST",
        f"/api/v1/workspaces/{tenant_id}/companies",
        json_body={"name": name, "kind": "company", "timezone": "Europe/Moscow"},
    )
    ok, actual = evaluate_http_status(created[0], 200)
    report.record(f"{step_prefix}.company.create", "HTTP 200", actual, ok)
    if not ok or not created[1]:
        return None
    company_id = created[1]["id"]
    if not billing_activate(client, company_id, report):
        return None
    return company_id


def run_acceptance() -> int:
    base = _env("STAGING_BASE_URL")
    if not base:
        base = input("STAGING_BASE_URL: ").strip()
    password = _env("STAGING_PASSWORD") or getpass.getpass("Пароль тестовых пользователей: ")

    postgres_hint = _env(
        "STAGING_POSTGRES_EXEC_HINT",
        "docker compose --env-file .env -f infra/docker-compose.prod.yml exec -T postgres "
        "psql -U finpilot -d finpilot",
    )

    owner_email = _env("STAGING_EMAIL_OWNER") or f"staging-owner-{secrets.token_hex(4)}@example.com"
    tenant_b_email = _env("STAGING_EMAIL_TENANT_B") or f"staging-tenantb-{secrets.token_hex(4)}@example.com"

    report = Report()
    client = HttpClient(base)

    live, _, _ = client.request("GET", "/health/live")
    ready, _, _ = client.request("GET", "/health/ready")
    ok_l, act_l = evaluate_http_status(live, 200)
    ok_r, act_r = evaluate_http_status(ready, 200)
    report.record("health.live", "HTTP 200", act_l, ok_l)
    report.record("health.ready", "HTTP 200", act_r, ok_r)

    reg = client.request(
        "POST",
        "/api/v1/auth/register",
        json_body={"email": owner_email, "password": password, "name": "Staging Owner"},
    )
    ok, act = evaluate_http_status(reg[0], 200)
    report.record("auth.register.owner", "HTTP 200", act, ok)
    print_sql_verify_hint(owner_email, postgres_hint or "")
    token_a = prompt_verify_token("STAGING_VERIFY_TOKEN_OWNER")
    verified = client.request("POST", "/api/v1/auth/verify-email", json_body={"token": token_a})
    ok_v, act_v = evaluate_http_status(verified[0], 200)
    report.record("auth.verify.owner", "HTTP 200", act_v, ok_v)

    logged = client.request(
        "POST",
        "/api/v1/auth/login",
        json_body={"email": owner_email, "password": password},
    )
    ok, act = evaluate_http_status(logged[0], 200)
    report.record("auth.login.owner", "HTTP 200", act, ok)
    if logged[1]:
        client.set_csrf(logged[1].get("csrf_token"))

    me = client.request("GET", "/api/v1/auth/me")
    verified_at = (me[1] or {}).get("email_verified_at") if me[0] == 200 else None
    report.record(
        "auth.me.owner",
        "email_verified_at задан",
        "set" if verified_at else "missing",
        bool(verified_at),
    )

    ws = client.request("POST", "/api/v1/workspaces", json_body={"name": "Staging acceptance A"})
    ok, act = evaluate_http_status(ws[0], 200)
    report.record("workspace.a", "HTTP 200", act, ok)
    tenant_a = (ws[1] or {}).get("id") if ws[1] else None
    if not tenant_a:
        write_report(report, owner_email, tenant_b_email)
        return 1

    company_a = setup_company(client, tenant_a, "Acceptance A", report, "org.a")
    if not company_a:
        write_report(report, owner_email, tenant_b_email)
        return 1

    ensure_revenue_source(client, company_a, "2026-10-31")
    report.record("revenue.source.a", "HTTP 200", "configured", True)
    post_sales_from_fixture(client, company_a)
    report.record("revenue.sales.october_gross", "POST 200", f"{FIXTURE_CSV.name} rows", True)

    dash_before = dashboard(client, company_a)
    flags = dash_before.get("quality_flags") if dash_before else None
    ok_f, act_f = evaluate_quality_flags(flags, want_unknown=True, want_from_profile=False)
    report.record("dashboard.before.flags", "unknown,!from_profile", act_f, ok_f)
    ok_m, act_m = evaluate_metric_basis(dash_before or {}, "source")
    report.record("dashboard.before.metric_basis", "source", act_m, ok_m)

    ar_before = receivable(client, company_a)
    ok_ar, act_ar = evaluate_quality_flags(
        ar_before.get("quality_flags") if ar_before else None,
        want_unknown=True,
        want_from_profile=False,
    )
    report.record("receivable.before.flags", "unknown,!from_profile", act_ar, ok_ar)

    patch_code = patch_profile_draft(client, company_a)
    ok_p, act_p = evaluate_http_status(patch_code, 200)
    report.record("profile.draft.patch", "HTTP 200", act_p, ok_p)
    dash_draft = dashboard(client, company_a)
    ok_d, act_d = evaluate_quality_flags(
        dash_draft.get("quality_flags") if dash_draft else None,
        want_unknown=True,
        want_from_profile=False,
    )
    report.record("dashboard.after_draft.flags", "как до confirm", act_d, ok_d)

    ok_c, act_c = evaluate_http_status(confirm_profile(client, company_a), 200)
    report.record("profile.confirm.na", "HTTP 200", act_c, ok_c)
    dash_after = dashboard(client, company_a)
    ok_af, act_af = evaluate_quality_flags(
        dash_after.get("quality_flags") if dash_after else None,
        want_unknown=False,
        want_from_profile=True,
    )
    report.record("dashboard.after_confirm.flags", "!unknown,from_profile", act_af, ok_af)
    ok_mb, act_mb = evaluate_metric_basis(dash_after or {}, "net")
    report.record("dashboard.after_confirm.metric_basis", "net", act_mb, ok_mb)

    ar_after = receivable(client, company_a)
    ok_ar2, act_ar2 = evaluate_quality_flags(
        ar_after.get("quality_flags") if ar_after else None,
        want_unknown=False,
        want_from_profile=True,
    )
    report.record("receivable.after_confirm.flags", "!unknown,from_profile", act_ar2, ok_ar2)

    patch_profile_draft(client, company_a, vat_status="special_rates_5_7")
    ok_sc, act_sc = evaluate_http_status(confirm_profile(client, company_a), 200)
    report.record("profile.confirm.special_rates", "HTTP 200", act_sc, ok_sc)
    dash_spec = dashboard(client, company_a)
    ok_sp, act_sp = evaluate_quality_flags(
        dash_spec.get("quality_flags") if dash_spec else None,
        want_unknown=True,
        want_from_profile=False,
    )
    report.record("dashboard.special_rates.flags", "unknown,!from_profile", act_sp, ok_sp)

    company_approach = setup_company(
        client, tenant_a, "Threshold approaching", report, "org.threshold.approaching"
    )
    if company_approach:
        ensure_revenue_source(client, company_approach, "2026-12-31")
        patch_profile_draft(client, company_approach)
        confirm_profile(client, company_approach)
        post_gross_sale(
            client,
            company_approach,
            day="2026-10-05",
            amount="16500000.00",
            doc="TH-APP",
        )
        dash_th = dashboard(client, company_approach, PERIOD_YTD_OCT)
        ok_th, act_th = evaluate_vat_threshold(dash_th or {}, present=True, status="approaching")
        report.record("vat_threshold.approaching", "status=approaching", act_th, ok_th)

    company_exceed = setup_company(
        client, tenant_a, "Threshold exceeded", report, "org.threshold.exceeded"
    )
    if company_exceed:
        ensure_revenue_source(client, company_exceed, "2026-12-31")
        patch_profile_draft(client, company_exceed)
        confirm_profile(client, company_exceed)
        post_gross_sale(
            client,
            company_exceed,
            day="2026-10-05",
            amount="21000000.00",
            doc="TH-EX",
        )
        dash_ex = dashboard(client, company_exceed, PERIOD_YTD_OCT)
        ok_ex, act_ex = evaluate_vat_threshold(dash_ex or {}, present=True, status="exceeded")
        report.record("vat_threshold.exceeded", "status=exceeded", act_ex, ok_ex)

    reg_b = client.request(
        "POST",
        "/api/v1/auth/register",
        json_body={"email": tenant_b_email, "password": password, "name": "Staging Tenant B"},
    )
    ok_b, act_b = evaluate_http_status(reg_b[0], 200)
    report.record("auth.register.tenant_b", "HTTP 200", act_b, ok_b)
    print_sql_verify_hint(tenant_b_email, postgres_hint or "")
    token_b = prompt_verify_token("STAGING_VERIFY_TOKEN_TENANT_B")
    client.request("POST", "/api/v1/auth/verify-email", json_body={"token": token_b})
    login_b = client.request(
        "POST",
        "/api/v1/auth/login",
        json_body={"email": tenant_b_email, "password": password},
    )
    client_b = HttpClient(base)
    if login_b[1]:
        client_b.set_csrf(login_b[1].get("csrf_token"))
    ws_b = client_b.request("POST", "/api/v1/workspaces", json_body={"name": "Staging acceptance B"})
    tenant_b = (ws_b[1] or {}).get("id") if ws_b[1] else None
    if tenant_b and company_a:
        client_b.set_tenant(tenant_b)
        foreign = client_b.request("GET", f"/api/v1/companies/{company_a}/dashboard", query=PERIOD_OCT)
        ok_iso, act_iso = evaluate_isolation_status(foreign[0])
        report.record("isolation.dashboard.foreign", "HTTP 404", act_iso, ok_iso)

    write_report(report, owner_email, tenant_b_email)
    print_report_table(report)
    return 0 if report.success else 1


def write_report(report: Report, owner_email: str, tenant_b_email: str) -> None:
    lines = [
        "# Staging acceptance report",
        "",
        f"- owner: {mask_email(owner_email)}",
        f"- tenant_b: {mask_email(tenant_b_email)}",
        "",
        "| Шаг | Ожидаемо | Фактически | Совпало |",
        "| --- | --- | --- | --- |",
    ]
    for row in report.rows:
        mark = "да" if row.ok else "**нет**"
        lines.append(f"| {row.step} | {row.expected} | {row.actual} | {mark} |")
    lines.append("")
    lines.append(f"Итог: **{'PASS' if report.success else 'FAIL'}**")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def print_report_table(report: Report) -> None:
    print("\n| Шаг | Ожидаемо | Фактически | Совпало |")
    print("| --- | --- | --- | --- |")
    for row in report.rows:
        mark = "да" if row.ok else "НЕТ"
        print(f"| {row.step} | {row.expected} | {row.actual} | {mark} |")
    print(f"\nОтчёт: {REPORT_PATH}")
    print(f"Итог: {'PASS' if report.success else 'FAIL'}")


if __name__ == "__main__":
    sys.exit(run_acceptance())
