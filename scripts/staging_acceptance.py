#!/usr/bin/env python3
"""Автоматизированная приёмка стенда по docs/runbook-staging-acceptance.md (только HTTP API).

Секреты: через окружение или файлы в /tmp/fp_*; в acceptance-report.md не попадают.
Зависимости: стандартная библиотека Python 3.12+.

HTTP-клиент для стенда с SESSION_COOKIE_SECURE=true: StagingCookiePolicy отправляет Secure-cookie
по plain HTTP — только для приёмочного контура, не для боевого браузера.

Переменные окружения (основные):
  STAGING_BASE_URL, STAGING_PASSWORD, STAGING_VERIFY_TOKEN_OWNER, STAGING_VERIFY_TOKEN_TENANT_B
  STAGING_SSH_ALIAS, STAGING_APP_ROOT — SQL-подсказка verify через ssh
  Без STAGING_VERIFY_TOKEN_*: ожидание /tmp/fp_verify_owner и /tmp/fp_verify_tenant_b
  STAGING_BILLING_MODE=checkout|sql — по умолчанию checkout (тестовая ЮKassa)
  STAGING_BILLING_COMPANIES (4), STAGING_SQL_AUTO_CONTINUE=1, STAGING_CHECKOUT_AUTO_CONTINUE=1
  STAGING_PROVIDER_PAYMENT_ID / STAGING_WEBHOOK_PAYMENT_OBJECT_ID — id ЮKassa; иначе /tmp/fp_provider_payment_id
  STAGING_SKIP_BILLING=1 — только activate (период уже выдан)
"""

from __future__ import annotations

import csv
import getpass
import http.cookiejar
import json
import os
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_CSV = REPO_ROOT / "fixtures" / "staging_sales_gross_only.csv"
REPORT_PATH = REPO_ROOT / "acceptance-report.md"
GRANT_SQL_PATH = REPO_ROOT / "scripts" / "staging_grant_entitlements.sql"

VERIFY_FILE_OWNER = Path("/tmp/fp_verify_owner")
VERIFY_FILE_TENANT_B = Path("/tmp/fp_verify_tenant_b")
PROVIDER_PAYMENT_ID_FILE = Path("/tmp/fp_provider_payment_id")
VERIFY_FILE_POLL_SEC = 2
VERIFY_FILE_TIMEOUT_SEC = 600

DEFAULT_PERIOD_START = "2026-10-01T00:00:00+00:00"
DEFAULT_PERIOD_END = "2026-11-30T23:59:59+00:00"

BILLING_ACTIVATION_WAIT_SEC = 120
BILLING_ACTIVATION_POLL_INTERVAL_SEC = 2

PERIOD_OCT = "date_from=2026-10-01&date_to=2026-10-31"
PERIOD_YTD_OCT = "date_from=2026-01-01&date_to=2026-10-31"
AS_OF_OCT = "2026-10-31"

# Фирмы в tenant A: основная, порог approaching, порог exceeded, спецставки
DEFAULT_BILLING_COMPANIES = 4

COMPANY_DEFINITIONS: tuple[tuple[str, str], ...] = (
    ("org.a", "Acceptance A"),
    ("org.threshold.approaching", "Threshold approaching"),
    ("org.threshold.exceeded", "Threshold exceeded"),
    ("org.special", "Acceptance special rates"),
)

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


class StagingCookiePolicy(http.cookiejar.DefaultCookiePolicy):
    """Разрешает отправку Secure-cookie на http:// (только стенд / приёмка)."""

    def return_ok(self, cookie, request):  # noqa: ANN001
        if cookie.secure and request.type == "http":
            return True
        return super().return_ok(cookie, request)


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    if value is not None and not value.strip():
        return default
    return value


def _env_flag(name: str) -> bool:
    return (_env(name, "") or "").lower() in {"1", "true", "yes"}


def mask_email(email: str) -> str:
    local, _, domain = email.partition("@")
    if not domain:
        return "***"
    shown = local[:2] if len(local) > 2 else "*"
    return f"{shown}***@{domain}"


def safe_exception_text(exc: BaseException) -> str:
    text = f"{type(exc).__name__}: {exc}"
    return text.replace("\n", " ")[:400]


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
        self.rows.append(StepResult(step, expected, actual, ok))

    @property
    def success(self) -> bool:
        return all(row.ok for row in self.rows)


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
        self._jar = CookieJar(policy=StagingCookiePolicy())
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


def build_verify_link_ssh_sql(email: str) -> str:
    safe_email = email.replace("'", "''")
    ssh_alias = _env("STAGING_SSH_ALIAS") or "SSH_ALIAS"
    app_root = _env("STAGING_APP_ROOT") or "/opt/finpilot"
    sql = (
        "SELECT payload_redacted->>'link' FROM transactional_email_outbox "
        f"WHERE type = 'verify_email' AND lower(to_email) = lower('{safe_email}') "
        "ORDER BY created_at DESC LIMIT 1"
    )
    inner = (
        f"cd {app_root} && docker compose --env-file .env "
        "-f infra/docker-compose.prod.yml -f infra/docker-compose.prod.ip.override.yml "
        f"exec -T postgres psql -U finpilot -d finpilot -t -A -c \"{sql}\""
    )
    return f"ssh {ssh_alias} '{inner}'"


def _parse_verify_token(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://"):
        query = urllib.parse.parse_qs(urllib.parse.urlparse(text).query)
        token = query.get("token", [""])[0]
        return token.strip()
    return text


def print_sql_verify_hint(email: str, token_file: Path) -> None:
    print("\n--- Подтверждение почты (SQL через SSH, с локальной машины) ---")
    print(build_verify_link_ssh_sql(email))
    print(
        f"Извлеките token из ссылки и запишите в {token_file} "
        f"(одна строка) или задайте переменную окружения. Токен не попадает в отчёт.\n"
    )


def wait_for_verify_token_file(path: Path) -> str | None:
    print(f"Ожидание токена в {path} (до {VERIFY_FILE_TIMEOUT_SEC // 60} мин, опрос {VERIFY_FILE_POLL_SEC} с)…")
    deadline = time.monotonic() + VERIFY_FILE_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if path.is_file():
            token = _parse_verify_token(path.read_text(encoding="utf-8"))
            if token:
                try:
                    path.unlink()
                except OSError:
                    pass
                return token
        time.sleep(VERIFY_FILE_POLL_SEC)
    return None


def resolve_verify_token(env_name: str, token_file: Path) -> str | None:
    from_env = (_env(env_name) or "").strip()
    if from_env:
        parsed = _parse_verify_token(from_env)
        return parsed or None
    return wait_for_verify_token_file(token_file)


def build_provider_payment_id_ssh_sql(payment_attempt_id: str) -> str:
    ssh_alias = _env("STAGING_SSH_ALIAS") or "SSH_ALIAS"
    app_root = _env("STAGING_APP_ROOT") or "/opt/finpilot"
    safe_id = payment_attempt_id.replace("'", "")
    sql = (
        "SELECT provider_payment_id FROM payment_attempts "
        f"WHERE id = '\\''{safe_id}'\\''::uuid"
    )
    return (
        f"ssh {ssh_alias} 'cd {app_root} && docker compose --env-file .env "
        "-f infra/docker-compose.prod.yml -f infra/docker-compose.prod.ip.override.yml "
        f"exec -T postgres psql -U finpilot -d finpilot -t -A -c \"{sql};\"'"
    )


def print_provider_payment_id_hint(payment_attempt_id: str) -> None:
    print("\n--- provider_payment_id для webhook (SQL через SSH, с локальной машины) ---")
    print(build_provider_payment_id_ssh_sql(payment_attempt_id))
    print(
        f"Запишите значение в {PROVIDER_PAYMENT_ID_FILE} (одна строка) "
        "или задайте STAGING_PROVIDER_PAYMENT_ID. Не попадает в отчёт.\n"
    )


def wait_for_provider_payment_id_file(path: Path = PROVIDER_PAYMENT_ID_FILE) -> str | None:
    print(
        f"Ожидание provider_payment_id в {path} "
        f"(до {VERIFY_FILE_TIMEOUT_SEC // 60} мин, опрос {VERIFY_FILE_POLL_SEC} с)…"
    )
    deadline = time.monotonic() + VERIFY_FILE_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if path.is_file():
            value = path.read_text(encoding="utf-8").strip()
            if value:
                try:
                    path.unlink()
                except OSError:
                    pass
                return value
        time.sleep(VERIFY_FILE_POLL_SEC)
    return None


def resolve_provider_payment_id(
    client: HttpClient,
    payment_attempt_id: str,
    report: Report,
) -> str | None:
    from_env = (_env("STAGING_PROVIDER_PAYMENT_ID") or _env("STAGING_WEBHOOK_PAYMENT_OBJECT_ID") or "").strip()
    if from_env:
        return from_env
    view = client.request("GET", f"/api/v1/billing/payments/{payment_attempt_id}")
    if view[0] == 200 and view[1]:
        from_api = (view[1] or {}).get("provider_payment_id")
        if from_api:
            report.record("billing.provider_id", "из API", "получен", True)
            return str(from_api).strip()
    print_provider_payment_id_hint(payment_attempt_id)
    value = wait_for_provider_payment_id_file()
    if value:
        return value
    report.record("billing.provider_id", "provider_payment_id", "не задан", False)
    return None


def load_gross_sales_csv(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for item in csv.DictReader(handle):
            rows.append(item)
    return rows


def user_email_verified(body: dict[str, Any] | None) -> bool:
    if not body:
        return False
    user = body.get("user")
    if isinstance(user, dict):
        return bool(user.get("email_verified"))
    return False


def check_auth_me(client: HttpClient, report: Report, label: str) -> bool:
    code, body, _ = client.request("GET", "/api/v1/auth/me")
    if code == 401:
        report.record(
            f"auth.me.{label}",
            "HTTP 200",
            "401 — сессионная cookie не отправляется (проверьте StagingCookiePolicy / SESSION_COOKIE_SECURE)",
            False,
        )
        return False
    ok, actual = evaluate_http_status(code, 200)
    verified = user_email_verified(body if isinstance(body, dict) else None)
    report.record(
        f"auth.me.{label}",
        "HTTP 200 + user.email_verified",
        actual if not ok else ("verified" if verified else "email_verified=false"),
        ok and verified,
    )
    return ok and verified


@dataclass
class TenantBilling:
    prepared: bool = False
    period_id: str | None = None


def resolve_billing_mode() -> str:
    mode = (_env("STAGING_BILLING_MODE", "") or "").strip().lower()
    if mode == "sql":
        return "sql"
    if mode == "checkout":
        return "checkout"
    if _env_flag("STAGING_SKIP_BILLING"):
        return "skip"
    return "checkout"


def recommend_sql_fallback(report: Report, reason: str) -> None:
    report.record(
        "billing.fallback",
        "STAGING_BILLING_MODE=sql",
        reason,
        True,
    )


def wait_for_checkout_payment() -> None:
    if _env_flag("STAGING_CHECKOUT_AUTO_CONTINUE"):
        return
    input("Оплатите тестовой картой по ссылке confirmation_url, затем нажмите Enter… ")


def _apply_sql_placeholders(text: str, mapping: dict[str, str]) -> str:
    for key, value in mapping.items():
        text = text.replace(key, value)
    return text


def render_staging_entitlement_sql(
    *,
    tenant_id: str,
    company_ids: list[str],
    period_id: str,
    company_limit: int,
    period_start: str = DEFAULT_PERIOD_START,
    period_end: str = DEFAULT_PERIOD_END,
) -> tuple[str, str]:
    raw = GRANT_SQL_PATH.read_text(encoding="utf-8")
    if "-- ===== ROLLBACK =====" not in raw:
        raise ValueError("staging_grant_entitlements.sql: нет секции ROLLBACK")
    grant_part, rollback_part = raw.split("-- ===== ROLLBACK =====", maxsplit=1)
    company_array = ", ".join(f"'{cid}'" for cid in company_ids)
    mapping = {
        "@TENANT_ID@": tenant_id,
        "@PERIOD_ID@": period_id,
        "@PERIOD_START@": period_start,
        "@PERIOD_END@": period_end,
        "@COMPANY_LIMIT@": str(company_limit),
        "@COMPANY_ID_ARRAY@": company_array,
    }
    grant_sql = _apply_sql_placeholders(grant_part.strip(), mapping)
    rollback_sql = _apply_sql_placeholders(
        rollback_part.replace("-- ===== ROLLBACK =====", "", 1).strip(),
        mapping,
    )
    return grant_sql, rollback_sql


def wait_for_sql_grant() -> None:
    if _env_flag("STAGING_SQL_AUTO_CONTINUE"):
        return
    input("Выполните SQL на стенде (GRANT), затем нажмите Enter… ")


def verify_finance_dashboard(
    client: HttpClient,
    company_id: str,
    report: Report,
    step: str,
) -> bool:
    code, _, _ = client.request("GET", f"/api/v1/companies/{company_id}/dashboard", query=PERIOD_OCT)
    ok = code == 200
    detail = str(code)
    if code in {402, 403}:
        detail = f"{code} (нет оплаченного доступа — проверьте GRANT SQL)"
    report.record(step, "HTTP 200", detail, ok)
    return ok


def prepare_tenant_billing_sql(
    client: HttpClient,
    report: Report,
    *,
    tenant_id: str,
    company_ids: list[str],
    company_limit: int,
) -> tuple[bool, str | None]:
    period_id = str(uuid4())
    grant_sql, rollback_sql = render_staging_entitlement_sql(
        tenant_id=tenant_id,
        company_ids=company_ids,
        period_id=period_id,
        company_limit=company_limit,
    )
    print("\n--- SQL GRANT (staging_grant_entitlements.sql) ---\n")
    print(grant_sql)
    print("\n--- SQL ROLLBACK (после приёмки) ---\n")
    print(rollback_sql)
    print("")
    wait_for_sql_grant()
    probe = company_ids[0] if company_ids else ""
    if probe and not verify_finance_dashboard(client, probe, report, "billing.sql.probe_dashboard"):
        return False, period_id
    report.record("billing.sql", "GRANT применён", f"period_id={period_id}", True)
    return True, period_id


def activate_all_companies(
    client: HttpClient,
    report: Report,
    company_ids: list[str],
    prefixes: tuple[str, ...],
) -> bool:
    ok_all = True
    for prefix, cid in zip(prefixes, company_ids):
        code, _, _ = client.request("POST", f"/api/v1/billing/companies/{cid}/activate")
        if code == 200:
            report.record(f"{prefix}.activate", "HTTP 200", str(code), True)
        elif code == 402:
            report.record(
                f"{prefix}.activate",
                "HTTP 200 или не требуется",
                "402 (entitlement уже в SQL)",
                True,
            )
        else:
            report.record(f"{prefix}.activate", "HTTP 200", str(code), False)
            ok_all = False
    return ok_all


def wait_for_payment_activated(
    client: HttpClient,
    payment_attempt_id: str,
    report: Report,
) -> bool:
    attempts = BILLING_ACTIVATION_WAIT_SEC // BILLING_ACTIVATION_POLL_INTERVAL_SEC
    for _ in range(attempts):
        view = client.request("GET", f"/api/v1/billing/payments/{payment_attempt_id}")
        if view[0] == 200 and (view[1] or {}).get("activated"):
            report.record(
                "billing.activation",
                "payment.activated=true",
                f"true (до {BILLING_ACTIVATION_WAIT_SEC} с)",
                True,
            )
            return True
        time.sleep(BILLING_ACTIVATION_POLL_INTERVAL_SEC)
    report.record(
        "billing.activation",
        "payment.activated=true",
        f"false (таймаут {BILLING_ACTIVATION_WAIT_SEC} с; worker billing.process_inbox?)",
        False,
    )
    return False


def prepare_tenant_billing_checkout(
    client: HttpClient,
    report: Report,
    *,
    company_ids: list[str],
    companies: int,
    postgres_hint: str,
) -> tuple[bool, str | None]:
    quoted = client.request(
        "POST",
        "/api/v1/billing/quote",
        json_body={"companies": companies, "interval": "month", "payable_amount": "1.00"},
    )
    ok_q, act_q = evaluate_http_status(quoted[0], 200)
    report.record("billing.quote", f"HTTP 200 (companies={companies})", act_q, ok_q)
    if not ok_q or not quoted[1]:
        recommend_sql_fallback(report, "quote не прошёл")
        return False, None

    checked = client.request(
        "POST",
        "/api/v1/billing/checkout",
        json_body={"quote_id": quoted[1]["id"], "offer_accepted": True, "discount_percent": "0"},
        idempotency=secrets.token_hex(16),
    )
    ok_c, act_c = evaluate_http_status(checked[0], 200)
    detail = act_c
    if checked[0] == 503:
        detail = (
            f"{act_c} (SEND_LIVE_PAYMENTS=false или провайдер отключён; "
            "см. runbook §3.2 — только тестовый магазин ЮKassa)"
        )
        report.record("billing.checkout", "HTTP 200", detail, False)
        recommend_sql_fallback(report, "checkout HTTP 503")
        return False, None
    report.record("billing.checkout", "HTTP 200", detail, ok_c)
    if not ok_c or not checked[1]:
        recommend_sql_fallback(report, f"checkout HTTP {checked[0]}")
        return False, None

    checkout_body = checked[1] or {}
    payment_attempt_id = str(checkout_body.get("payment_id", ""))
    confirmation_url = checkout_body.get("confirmation_url")
    if confirmation_url:
        print("\n--- Оплата (тестовая ЮKassa) ---\n")
        print(confirmation_url)
        print("")
        report.record("billing.checkout.confirmation_url", "напечатан", "да", True)
    else:
        report.record(
            "billing.checkout.confirmation_url",
            "напечатан",
            "нет в ответе checkout",
            False,
        )

    wait_for_checkout_payment()

    provider_id = resolve_provider_payment_id(client, payment_attempt_id, report)
    if not provider_id:
        print(
            "Ошибка: пустой provider_payment_id — задайте STAGING_PROVIDER_PAYMENT_ID "
            f"или запишите id в {PROVIDER_PAYMENT_ID_FILE}.",
            file=sys.stderr,
        )
        recommend_sql_fallback(report, "нет provider_payment_id для webhook")
        return False, None

    webhook = client.request(
        "POST",
        "/api/v1/integrations/yookassa/webhook",
        json_body={"event": "payment.succeeded", "object": {"id": provider_id}},
    )
    ok_w, act_w = evaluate_http_status(webhook[0], 200)
    report.record("billing.webhook", "HTTP 200", act_w, ok_w)
    if not ok_w:
        recommend_sql_fallback(report, "webhook payment.succeeded не принят")
        return False, None

    activated = wait_for_payment_activated(client, payment_attempt_id, report)
    if not activated:
        recommend_sql_fallback(
            report,
            f"нет activated=true за {BILLING_ACTIVATION_WAIT_SEC} с — повторите или STAGING_BILLING_MODE=sql",
        )
        return False, None

    activate_all_companies(
        client,
        report,
        company_ids,
        tuple(item[0] for item in COMPANY_DEFINITIONS),
    )
    return True, None


def prepare_tenant_billing(
    client: HttpClient,
    report: Report,
    *,
    tenant_id: str,
    company_ids: list[str],
    companies: int,
    postgres_hint: str,
) -> tuple[bool, str | None]:
    mode = resolve_billing_mode()
    report.record("billing.mode", "sql|checkout|skip", mode, True)
    if mode == "skip":
        report.record(
            "billing.prepare",
            "skip (STAGING_SKIP_BILLING=1)",
            f"slots={companies}",
            True,
        )
        activate_all_companies(
            client,
            report,
            company_ids,
            tuple(item[0] for item in COMPANY_DEFINITIONS),
        )
        return True, None
    if mode == "sql":
        prepared, period_id = prepare_tenant_billing_sql(
            client,
            report,
            tenant_id=tenant_id,
            company_ids=company_ids,
            company_limit=companies,
        )
        if prepared:
            activate_all_companies(
                client,
                report,
                company_ids,
                tuple(item[0] for item in COMPANY_DEFINITIONS),
            )
        return prepared, period_id

    return prepare_tenant_billing_checkout(
        client,
        report,
        company_ids=company_ids,
        companies=companies,
        postgres_hint=postgres_hint,
    )


def activate_company_slot(
    client: HttpClient,
    company_id: str,
    report: Report,
    step_prefix: str,
) -> bool:
    activated = client.request("POST", f"/api/v1/billing/companies/{company_id}/activate")
    ok, actual = evaluate_http_status(activated[0], 200)
    report.record(f"{step_prefix}.activate", "HTTP 200", actual, ok)
    return ok


def create_company(
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
    report.record(f"{step_prefix}.create", "HTTP 200", actual, ok)
    if not ok or not created[1]:
        return None
    return str(created[1]["id"])


def ensure_revenue_source(
    client: HttpClient,
    company_id: str,
    coverage: str,
    report: Report,
    step_prefix: str,
) -> bool:
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
    ok_s, act_s = evaluate_http_status(source[0], 200)
    report.record(f"{step_prefix}.source", "HTTP 200", act_s, ok_s)
    if not ok_s or not source[1]:
        return False
    sid = source[1].get("id")
    covered = client.request(
        "POST",
        f"/api/v1/companies/{company_id}/sources/{sid}/coverage",
        json_body={"coverage_through": coverage},
    )
    ok_c, act_c = evaluate_http_status(covered[0], 200)
    report.record(f"{step_prefix}.coverage", f"coverage_through={coverage}", act_c, ok_c)
    return ok_c


def post_gross_sale(
    client: HttpClient,
    company_id: str,
    report: Report,
    step_prefix: str,
    *,
    day: str,
    amount: str,
    doc: str,
    key: str | None = None,
) -> bool:
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
    ok, actual = evaluate_http_status(created[0], 200)
    report.record(f"{step_prefix}.revenue", "HTTP 200", actual, ok)
    return ok


def post_sales_from_fixture(client: HttpClient, company_id: str, report: Report, prefix: str) -> bool:
    ok_all = True
    for row in load_gross_sales_csv(FIXTURE_CSV):
        ok = post_gross_sale(
            client,
            company_id,
            report,
            f"{prefix}.{row['external_id']}",
            day=row["recognition_date"],
            amount=row["amount_inc_vat"],
            doc=row["document_number"],
            key=row["external_id"],
        )
        ok_all = ok_all and ok
    return ok_all


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


def run_special_rates_scenario(
    client: HttpClient,
    company_id: str | None,
    billing: TenantBilling,
    report: Report,
) -> None:
    if not company_id:
        return
    if not billing.prepared:
        report.record("org.special", "billing prepared", "billing не подготовлен", False)
        return
    if ensure_revenue_source(client, company_id, "2026-10-31", report, "org.special"):
        post_gross_sale(
            client,
            company_id,
            report,
            "org.special.sale",
            day="2026-10-10",
            amount="105000.00",
            doc="SP-1",
        )
        ok_p, act_p = evaluate_http_status(
            patch_profile_draft(client, company_id, vat_status="special_rates_5_7"), 200
        )
        report.record("org.special.profile.draft", "HTTP 200", act_p, ok_p)
        ok_c, act_c = evaluate_http_status(confirm_profile(client, company_id), 200)
        report.record("org.special.profile.confirm", "HTTP 200", act_c, ok_c)
        dash = dashboard(client, company_id)
        ok_d, act_d = evaluate_quality_flags(
            dash.get("quality_flags") if dash else None,
            want_unknown=True,
            want_from_profile=False,
        )
        report.record("org.special.dashboard.flags", "unknown,!from_profile", act_d, ok_d)
        ar = receivable(client, company_id)
        ok_a, act_a = evaluate_quality_flags(
            ar.get("quality_flags") if ar else None,
            want_unknown=True,
            want_from_profile=False,
        )
        report.record("org.special.receivable.flags", "unknown,!from_profile", act_a, ok_a)


def register_verify_login_tenant_b(
    base: str,
    report: Report,
    *,
    tenant_b_email: str,
    password: str,
) -> tuple[HttpClient | None, int | None]:
    """Register → SQL-подсказка → токен → verify → login → auth/me."""
    client = HttpClient(base)
    reg_b = client.request(
        "POST",
        "/api/v1/auth/register",
        json_body={"email": tenant_b_email, "password": password, "name": "Staging Tenant B"},
    )
    ok_b, act_b = evaluate_http_status(reg_b[0], 200)
    report.record("auth.register.tenant_b", "HTTP 200", act_b, ok_b)
    if not ok_b:
        return None, reg_b[0] or 1

    print_sql_verify_hint(tenant_b_email, VERIFY_FILE_TENANT_B)
    token_b = resolve_verify_token("STAGING_VERIFY_TOKEN_TENANT_B", VERIFY_FILE_TENANT_B)
    if not token_b:
        print(
            f"Ошибка: пустой токен для tenant B — задайте STAGING_VERIFY_TOKEN_TENANT_B "
            f"или запишите токен в {VERIFY_FILE_TENANT_B}.",
            file=sys.stderr,
        )
        report.record("auth.verify.tenant_b", "токен задан", "не получен", False)
        return None, 1

    verified_b = client.request("POST", "/api/v1/auth/verify-email", json_body={"token": token_b})
    report.record("auth.verify.tenant_b", "HTTP 200", str(verified_b[0]), verified_b[0] == 200)
    if verified_b[0] != 200:
        return None, verified_b[0] or 1

    login_b = client.request(
        "POST",
        "/api/v1/auth/login",
        json_body={"email": tenant_b_email, "password": password},
    )
    ok_login, act_login = evaluate_http_status(login_b[0], 200)
    report.record("auth.login.tenant_b", "HTTP 200", act_login, ok_login)
    if not ok_login:
        return None, login_b[0] or 1
    if login_b[1]:
        client.set_csrf(login_b[1].get("csrf_token"))
    if not check_auth_me(client, report, "tenant_b"):
        return None, 1
    return client, None


def run_acceptance_body(
    report: Report,
    *,
    base: str,
    password: str,
    postgres_hint: str,
    owner_email: str,
    tenant_b_email: str,
) -> int:
    client = HttpClient(base)
    billing = TenantBilling()

    live, _, _ = client.request("GET", "/health/live")
    ready, _, _ = client.request("GET", "/health/ready")
    report.record("health.live", "HTTP 200", str(live), live == 200)
    report.record("health.ready", "HTTP 200", str(ready), ready == 200)

    reg = client.request(
        "POST",
        "/api/v1/auth/register",
        json_body={"email": owner_email, "password": password, "name": "Staging Owner"},
    )
    ok, act = evaluate_http_status(reg[0], 200)
    report.record("auth.register.owner", "HTTP 200", act, ok)
    print_sql_verify_hint(owner_email, VERIFY_FILE_OWNER)
    token_a = resolve_verify_token("STAGING_VERIFY_TOKEN_OWNER", VERIFY_FILE_OWNER)
    if not token_a:
        print(
            f"Ошибка: пустой токен для owner — задайте STAGING_VERIFY_TOKEN_OWNER "
            f"или запишите токен в {VERIFY_FILE_OWNER}.",
            file=sys.stderr,
        )
        report.record("auth.verify.owner", "токен задан", "не получен", False)
        return 1
    verified = client.request("POST", "/api/v1/auth/verify-email", json_body={"token": token_a})
    report.record("auth.verify.owner", "HTTP 200", str(verified[0]), verified[0] == 200)

    logged = client.request(
        "POST",
        "/api/v1/auth/login",
        json_body={"email": owner_email, "password": password},
    )
    ok, act = evaluate_http_status(logged[0], 200)
    report.record("auth.login.owner", "HTTP 200", act, ok)
    if logged[1]:
        client.set_csrf(logged[1].get("csrf_token"))
    if not check_auth_me(client, report, "owner"):
        return 1

    ws = client.request("POST", "/api/v1/workspaces", json_body={"name": "Staging acceptance A"})
    ok, act = evaluate_http_status(ws[0], 200)
    report.record("workspace.a", "HTTP 200", act, ok)
    tenant_a = (ws[1] or {}).get("id") if ws[1] else None
    if not tenant_a:
        return 1

    company_ids: list[str] = []
    client.set_tenant(tenant_a)
    for prefix, name in COMPANY_DEFINITIONS:
        cid = create_company(client, tenant_a, name, report, prefix)
        if cid:
            company_ids.append(cid)

    n_slots = max(
        int(_env("STAGING_BILLING_COMPANIES", str(DEFAULT_BILLING_COMPANIES))),
        len(company_ids),
    )
    billing.prepared, billing.period_id = prepare_tenant_billing(
        client,
        report,
        tenant_id=tenant_a,
        company_ids=company_ids,
        companies=n_slots,
        postgres_hint=postgres_hint,
    )
    if not billing.prepared and resolve_billing_mode() == "checkout":
        print(
            "Ошибка: checkout не завершён (нет provider_payment_id или другая ошибка биллинга); "
            "прогон остановлен. См. billing.fallback или STAGING_BILLING_MODE=sql.",
            file=sys.stderr,
        )
        return 1

    if not company_ids:
        return 1
    company_a = company_ids[0]

    if not ensure_revenue_source(client, company_a, "2026-10-31", report, "org.a"):
        return 1
    post_sales_from_fixture(client, company_a, report, "org.a")

    dash_before = dashboard(client, company_a)
    ok_f, act_f = evaluate_quality_flags(
        dash_before.get("quality_flags") if dash_before else None,
        want_unknown=True,
        want_from_profile=False,
    )
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

    ok_p, act_p = evaluate_http_status(patch_profile_draft(client, company_a), 200)
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

    special_id = company_ids[3] if len(company_ids) > 3 else None
    run_special_rates_scenario(client, special_id, billing, report)

    if len(company_ids) > 1:
        company_approach = company_ids[1]
        ensure_revenue_source(client, company_approach, "2026-12-31", report, "org.threshold.approaching")
        patch_profile_draft(client, company_approach)
        confirm_profile(client, company_approach)
        post_gross_sale(
            client,
            company_approach,
            report,
            "org.threshold.approaching.ytd",
            day="2026-10-05",
            amount="16500000.00",
            doc="TH-APP",
        )
        dash_th = dashboard(client, company_approach, PERIOD_YTD_OCT)
        ok_th, act_th = evaluate_vat_threshold(dash_th or {}, present=True, status="approaching")
        report.record("vat_threshold.approaching", "status=approaching", act_th, ok_th)

    if len(company_ids) > 2:
        company_exceed = company_ids[2]
        ensure_revenue_source(client, company_exceed, "2026-12-31", report, "org.threshold.exceeded")
        patch_profile_draft(client, company_exceed)
        confirm_profile(client, company_exceed)
        post_gross_sale(
            client,
            company_exceed,
            report,
            "org.threshold.exceeded.ytd",
            day="2026-10-05",
            amount="21000000.00",
            doc="TH-EX",
        )
        dash_ex = dashboard(client, company_exceed, PERIOD_YTD_OCT)
        ok_ex, act_ex = evaluate_vat_threshold(dash_ex or {}, present=True, status="exceeded")
        report.record("vat_threshold.exceeded", "status=exceeded", act_ex, ok_ex)

    client_b, tenant_b_exit = register_verify_login_tenant_b(
        base,
        report,
        tenant_b_email=tenant_b_email,
        password=password,
    )
    if tenant_b_exit is not None:
        return tenant_b_exit
    assert client_b is not None
    ws_b = client_b.request("POST", "/api/v1/workspaces", json_body={"name": "Staging acceptance B"})
    tenant_b = (ws_b[1] or {}).get("id") if ws_b[1] else None
    if tenant_b:
        client_b.set_tenant(tenant_b)
        foreign = client_b.request("GET", f"/api/v1/companies/{company_a}/dashboard", query=PERIOD_OCT)
        ok_iso, act_iso = evaluate_isolation_status(foreign[0])
        report.record("isolation.dashboard.foreign", "HTTP 404", act_iso, ok_iso)

    return 0 if report.success else 1


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
    exit_code = 1
    try:
        exit_code = run_acceptance_body(
            report,
            base=base,
            password=password,
            postgres_hint=postgres_hint or "",
            owner_email=owner_email,
            tenant_b_email=tenant_b_email,
        )
    except Exception as exc:
        report.record("fatal", "без исключения", safe_exception_text(exc), False)
        exit_code = 1
    finally:
        write_report(report, owner_email, tenant_b_email)
        print_report_table(report)
    return exit_code


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
