"""Локальные тесты логики scripts/staging_acceptance.py (без HTTP к стенду)."""

from __future__ import annotations

import importlib.util
import http.cookiejar
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parent
MODULE_PATH = SCRIPTS / "staging_acceptance.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("staging_acceptance", MODULE_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["staging_acceptance"] = mod
    spec.loader.exec_module(mod)
    return mod


class StagingAcceptanceLogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_module()

    def test_quality_flags_before_confirm(self) -> None:
        flags = ["vat_basis_unknown", "partial_period"]
        ok, detail = self.mod.evaluate_quality_flags(
            flags, want_unknown=True, want_from_profile=False
        )
        self.assertTrue(ok, detail)

    def test_quality_flags_after_confirm(self) -> None:
        flags = ["vat_basis_from_profile"]
        ok, detail = self.mod.evaluate_quality_flags(
            flags, want_unknown=False, want_from_profile=True
        )
        self.assertTrue(ok, detail)

    def test_vat_threshold_approaching(self) -> None:
        body = {"vat_threshold": {"status": "approaching", "ytd_revenue": "16500000.00"}}
        ok, detail = self.mod.evaluate_vat_threshold(body, present=True, status="approaching")
        self.assertTrue(ok, detail)

    def test_vat_threshold_absent(self) -> None:
        ok, detail = self.mod.evaluate_vat_threshold({}, present=False)
        self.assertTrue(ok, detail)

    def test_isolation_404(self) -> None:
        ok, detail = self.mod.evaluate_isolation_status(404)
        self.assertTrue(ok, detail)
        ok2, _ = self.mod.evaluate_isolation_status(200)
        self.assertFalse(ok2)

    def test_mask_email_hides_local(self) -> None:
        masked = self.mod.mask_email("owner.test@example.com")
        self.assertNotIn("owner.test", masked)
        self.assertIn("@example.com", masked)

    def test_report_no_secrets(self) -> None:
        report = self.mod.Report()
        report.record("step", "exp", "act", True)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "acceptance-report.md"
            with patch.object(self.mod, "REPORT_PATH", path):
                self.mod.write_report(report, "secret@example.com", "b@example.com")
                text = path.read_text(encoding="utf-8")
        self.assertNotIn("secret@", text)
        self.assertIn("***@", text)

    def test_report_written_on_exception(self) -> None:
        mod = self.mod
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "acceptance-report.md"
            with patch.object(mod, "REPORT_PATH", path):
                with patch.object(mod, "run_acceptance_body", side_effect=RuntimeError("boom test")):
                    with patch.dict(
                        "os.environ",
                        {
                            "STAGING_BASE_URL": "http://example.test",
                            "STAGING_PASSWORD": "pw-local-test-only",
                            "STAGING_VERIFY_TOKEN_OWNER": "t",
                            "STAGING_VERIFY_TOKEN_TENANT_B": "t",
                        },
                        clear=False,
                    ):
                        code = mod.run_acceptance()
            self.assertEqual(code, 1)
            text = path.read_text(encoding="utf-8")
            self.assertIn("fatal", text)
            self.assertIn("RuntimeError", text)
            self.assertNotIn("pw-local-test-only", text)

    def test_cookie_policy_allows_secure_on_http(self) -> None:
        policy = self.mod.StagingCookiePolicy()
        cookie = http.cookiejar.Cookie(
            version=0,
            name="s",
            value="v",
            port=None,
            port_specified=False,
            domain="example.test",
            domain_specified=True,
            domain_initial_dot=False,
            path="/",
            path_specified=True,
            secure=True,
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        )
        req = MagicMock()
        req.type = "http"
        self.assertTrue(policy.return_ok(cookie, req))


class StagingAcceptanceSpecialRatesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_module()

    def test_special_rates_flags_from_mock_dashboard(self) -> None:
        body = {"quality_flags": ["vat_basis_unknown"], "metric_basis": "source"}
        ok, detail = self.mod.evaluate_quality_flags(
            body["quality_flags"], want_unknown=True, want_from_profile=False
        )
        self.assertTrue(ok, detail)

    def test_special_rates_flow_mock_http(self) -> None:
        mod = self.mod
        report = mod.Report()
        client = MagicMock()
        billing = mod.TenantBilling(prepared=True)
        client.request.side_effect = [
            (200, {"id": "company-special"}, ""),
            (200, {"csrf_token": "c"}, ""),
        ]
        with (
            patch.object(mod, "ensure_revenue_source", return_value=True),
            patch.object(mod, "post_gross_sale", return_value=True),
            patch.object(mod, "patch_profile_draft", return_value=200),
            patch.object(mod, "confirm_profile", return_value=200),
            patch.object(
                mod,
                "dashboard",
                return_value={"quality_flags": ["vat_basis_unknown"], "metric_basis": "source"},
            ),
            patch.object(
                mod,
                "receivable",
                return_value={"quality_flags": ["vat_basis_unknown"]},
            ),
        ):
            mod.run_special_rates_scenario(client, "company-special", billing, report)
        names = [row.step for row in report.rows]
        self.assertIn("org.special.dashboard.flags", names)
        self.assertTrue(any(row.step == "org.special.dashboard.flags" and row.ok for row in report.rows))


class StagingAcceptanceDryHttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_module()

    def test_health_check_mocked(self) -> None:
        client = self.mod.HttpClient("http://example.test")
        fake_resp = MagicMock()
        fake_resp.status = 200
        fake_resp.read.return_value = b'{"status":"ok"}'
        fake_resp.__enter__ = lambda s: s
        fake_resp.__exit__ = MagicMock(return_value=False)
        with patch.object(client._opener, "open", return_value=fake_resp):
            code, body, _ = client.request("GET", "/health/live")
        self.assertEqual(code, 200)
        self.assertEqual(body, {"status": "ok"})


class StagingBillingSqlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_module()

    def test_resolve_billing_mode_default_checkout(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(self.mod.resolve_billing_mode(), "checkout")

    def test_resolve_billing_mode_explicit_sql(self) -> None:
        with patch.dict("os.environ", {"STAGING_BILLING_MODE": "sql"}, clear=True):
            self.assertEqual(self.mod.resolve_billing_mode(), "sql")

    def test_resolve_billing_mode_checkout_env(self) -> None:
        with patch.dict(
            "os.environ",
            {"STAGING_BILLING_MODE": "checkout"},
            clear=True,
        ):
            self.assertEqual(self.mod.resolve_billing_mode(), "checkout")

    def test_render_sql_contains_tenant_and_company_ids(self) -> None:
        tenant = "11111111-1111-4111-8111-111111111111"
        companies = [
            "22222222-2222-4222-8222-222222222222",
            "33333333-3333-4333-8333-333333333333",
        ]
        period = "44444444-4444-4444-8444-444444444444"
        grant, rollback = self.mod.render_staging_entitlement_sql(
            tenant_id=tenant,
            company_ids=companies,
            period_id=period,
            company_limit=4,
        )
        self.assertIn(tenant, grant)
        self.assertIn(companies[0], grant)
        self.assertIn(period, rollback)
        self.assertIn("DELETE FROM company_entitlements", rollback)

    def test_sql_billing_flow_mock_http(self) -> None:
        mod = self.mod
        report = mod.Report()
        client = MagicMock()
        tenant = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
        companies = ["bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"]
        call_log: list[tuple[str, str]] = []

        def fake_request(method: str, path: str, **kwargs: object) -> tuple[int, dict | None, str]:
            call_log.append((method, path))
            if method == "GET" and "/dashboard" in path:
                return 200, {"quality_flags": []}, ""
            if method == "POST" and "/activate" in path:
                return 200, {}, ""
            return 500, None, ""

        client.request.side_effect = fake_request

        with (
            patch.dict("os.environ", {"STAGING_SQL_AUTO_CONTINUE": "1"}, clear=False),
            patch.object(mod, "resolve_billing_mode", return_value="sql"),
            patch("builtins.print"),
        ):
            prepared, period_id = mod.prepare_tenant_billing(
                client,
                report,
                tenant_id=tenant,
                company_ids=companies,
                companies=1,
                postgres_hint="psql",
            )
        self.assertTrue(prepared)
        self.assertIsNotNone(period_id)
        methods = [item[0] for item in call_log]
        self.assertIn("GET", methods)
        self.assertIn("POST", methods)
        self.assertTrue(any(row.step == "billing.sql" and row.ok for row in report.rows))

    def test_checkout_503_recommends_sql(self) -> None:
        mod = self.mod
        report = mod.Report()
        client = MagicMock()
        client.request.side_effect = [
            (200, {"id": "quote-1"}, ""),
            (503, None, "disabled"),
        ]
        with patch.object(mod, "resolve_billing_mode", return_value="checkout"):
            prepared, _ = mod.prepare_tenant_billing(
                client,
                report,
                tenant_id="t",
                company_ids=["c1"],
                companies=1,
                postgres_hint="psql",
            )
        self.assertFalse(prepared)
        self.assertTrue(any(row.step == "billing.fallback" for row in report.rows))

    def test_checkout_flow_mock_http(self) -> None:
        mod = self.mod
        report = mod.Report()
        client = MagicMock()
        payment_id = "pay-attempt-1"
        poll_calls = {"n": 0}

        def fake_request(method: str, path: str, **kwargs: object) -> tuple[int, dict | None, str]:
            if method == "POST" and path.endswith("/quote"):
                return 200, {"id": "quote-1"}, ""
            if method == "POST" and path.endswith("/checkout"):
                return 200, {
                    "payment_id": payment_id,
                    "confirmation_url": "https://yookassa.test/pay/abc",
                }, ""
            if method == "GET" and f"/payments/{payment_id}" in path:
                poll_calls["n"] += 1
                if poll_calls["n"] >= 2:
                    return 200, {"activated": True}, ""
                return 200, {"activated": False}, ""
            if method == "POST" and "webhook" in path:
                return 200, {}, ""
            if method == "POST" and "/activate" in path:
                return 200, {}, ""
            return 500, None, ""

        client.request.side_effect = fake_request

        with (
            patch.dict(
                "os.environ",
                {
                    "STAGING_PROVIDER_PAYMENT_ID": "yk-provider-1",
                    "STAGING_CHECKOUT_AUTO_CONTINUE": "1",
                },
                clear=False,
            ),
            patch.object(mod, "resolve_billing_mode", return_value="checkout"),
            patch("time.sleep", return_value=None),
            patch("builtins.print"),
        ):
            prepared, period_id = mod.prepare_tenant_billing(
                client,
                report,
                tenant_id="tenant-1",
                company_ids=["c1"],
                companies=1,
                postgres_hint="psql",
            )
        self.assertTrue(prepared)
        self.assertIsNone(period_id)
        steps = [row.step for row in report.rows]
        self.assertIn("billing.checkout.confirmation_url", steps)
        self.assertIn("billing.webhook", steps)
        self.assertTrue(any(row.step == "billing.activation" and row.ok for row in report.rows))


class StagingVerifyTokenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_module()

    def test_parse_verify_token_from_url(self) -> None:
        url = "http://example.test/verify-email?token=abc-123"
        self.assertEqual(self.mod._parse_verify_token(url), "abc-123")

    def test_resolve_verify_token_from_env(self) -> None:
        with patch.dict("os.environ", {"STAGING_VERIFY_TOKEN_OWNER": "env-token"}, clear=False):
            token = self.mod.resolve_verify_token(
                "STAGING_VERIFY_TOKEN_OWNER",
                self.mod.VERIFY_FILE_OWNER,
            )
        self.assertEqual(token, "env-token")

    def test_wait_for_verify_token_file_reads_and_deletes(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            path = Path(tmp.name)
        try:
            path.write_text("file-token\n", encoding="utf-8")
            with patch.object(self.mod, "time") as mock_time:
                mock_time.monotonic.side_effect = [0.0, 0.0]
                mock_time.sleep = MagicMock()
                token = self.mod.wait_for_verify_token_file(path)
            self.assertEqual(token, "file-token")
            self.assertFalse(path.exists())
        finally:
            if path.exists():
                path.unlink()

    def test_verify_ssh_hint_starts_with_ssh(self) -> None:
        cmd = self.mod.build_verify_link_ssh_sql("user@example.com")
        self.assertTrue(cmd.startswith("ssh "))
        self.assertIn("exec -T postgres", cmd)
        self.assertIn("user@example.com", cmd)


class StagingProviderPaymentIdTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_module()

    def test_build_provider_sql_ssh_uses_squote_escape(self) -> None:
        cmd = self.mod.build_provider_payment_id_ssh_sql("11111111-1111-4111-8111-111111111111")
        self.assertTrue(cmd.startswith("ssh "))
        self.assertIn("'\\''", cmd)
        self.assertIn("provider_payment_id", cmd)
        self.assertIn("11111111-1111-4111-8111-111111111111", cmd)

    def test_resolve_provider_from_env(self) -> None:
        client = MagicMock()
        with patch.dict("os.environ", {"STAGING_PROVIDER_PAYMENT_ID": "yk-123"}, clear=False):
            value = self.mod.resolve_provider_payment_id(client, "pay-1", self.mod.Report())
        self.assertEqual(value, "yk-123")
        client.request.assert_not_called()

    def test_wait_for_provider_payment_file(self) -> None:
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            path = Path(tmp.name)
        try:
            path.write_text("prov-id\n", encoding="utf-8")
            with patch.object(self.mod, "PROVIDER_PAYMENT_ID_FILE", path):
                with patch.object(self.mod, "time") as mock_time:
                    mock_time.monotonic.side_effect = [0.0, 0.0]
                    mock_time.sleep = MagicMock()
                    value = self.mod.wait_for_provider_payment_id_file(path)
            self.assertEqual(value, "prov-id")
            self.assertFalse(path.exists())
        finally:
            if path.exists():
                path.unlink()

    def test_checkout_stops_when_provider_missing(self) -> None:
        mod = self.mod
        report = mod.Report()
        client = MagicMock()
        client.request.side_effect = [
            (200, {"id": "quote-1"}, ""),
            (200, {"payment_id": "p1", "confirmation_url": "https://pay.test/x"}, ""),
            (200, {"activated": False}, ""),
        ]
        with (
            patch.object(mod, "wait_for_checkout_payment"),
            patch.object(mod, "resolve_provider_payment_id", return_value=None),
            patch("builtins.print"),
        ):
            prepared, _ = mod.prepare_tenant_billing_checkout(
                client,
                report,
                company_ids=["c1"],
                companies=1,
                postgres_hint="",
            )
        self.assertFalse(prepared)
        self.assertTrue(any(row.step == "billing.fallback" for row in report.rows))


class StagingTenantBAuthOrderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_module()

    def test_tenant_b_register_before_hint_and_token(self) -> None:
        mod = self.mod
        events: list[str] = []
        mock_client = MagicMock()

        def fake_request(method: str, path: str, **kwargs: object) -> tuple[int, dict | None, str]:
            if method == "POST" and path == "/api/v1/auth/register":
                events.append("register")
                return 200, {"status": "ok"}, ""
            if method == "POST" and path == "/api/v1/auth/verify-email":
                events.append("verify")
                return 200, {"status": "ok"}, ""
            if method == "POST" and path == "/api/v1/auth/login":
                events.append("login")
                return 200, {"csrf_token": "csrf"}, ""
            if method == "GET" and path == "/api/v1/auth/me":
                events.append("me")
                return 200, {"user": {"email_verified": True}}, ""
            return 500, None, ""

        mock_client.request.side_effect = fake_request

        def hint(*_args: object, **_kwargs: object) -> None:
            events.append("hint")

        def token(*_args: object, **_kwargs: object) -> str:
            events.append("token")
            return "test-token"

        with (
            patch.object(mod, "HttpClient", return_value=mock_client),
            patch.object(mod, "print_sql_verify_hint", side_effect=hint),
            patch.object(mod, "resolve_verify_token", side_effect=token),
        ):
            client, exit_code = mod.register_verify_login_tenant_b(
                "http://example.test",
                mod.Report(),
                tenant_b_email="acc-tenantb@example.com",
                password="pw",
            )
        self.assertIsNone(exit_code)
        self.assertIs(client, mock_client)
        self.assertEqual(events, ["register", "hint", "token", "verify", "login", "me"])

    def test_tenant_b_register_failure_skips_hint(self) -> None:
        mod = self.mod
        events: list[str] = []
        mock_client = MagicMock()
        mock_client.request.return_value = (409, {"code": "conflict"}, "conflict")

        with (
            patch.object(mod, "HttpClient", return_value=mock_client),
            patch.object(mod, "print_sql_verify_hint", side_effect=lambda *_a, **_k: events.append("hint")),
        ):
            client, exit_code = mod.register_verify_login_tenant_b(
                "http://example.test",
                mod.Report(),
                tenant_b_email="acc-tenantb@example.com",
                password="pw",
            )
        self.assertIsNone(client)
        self.assertEqual(exit_code, 409)
        self.assertEqual(events, [])


class StagingAuthMeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_module()

    def test_user_email_verified_reads_nested_field(self) -> None:
        body = {"user": {"email_verified": True}, "csrf_token": "x", "memberships": []}
        self.assertTrue(self.mod.user_email_verified(body))

    def test_user_email_verified_false_when_missing(self) -> None:
        self.assertFalse(self.mod.user_email_verified({"user": {"email_verified": False}}))
        self.assertFalse(self.mod.user_email_verified({"email_verified_at": "2020-01-01"}))

    def test_check_auth_me_mock(self) -> None:
        report = self.mod.Report()
        client = MagicMock()
        client.request.return_value = (
            200,
            {
                "csrf_token": "secret",
                "user": {"id": "u1", "email": "a@b.com", "name": "A", "email_verified": True},
                "memberships": [],
            },
            "",
        )
        ok = self.mod.check_auth_me(client, report, "owner")
        self.assertTrue(ok)
        row = report.rows[-1]
        self.assertEqual(row.step, "auth.me.owner")
        self.assertTrue(row.ok)
        self.assertIn("verified", row.actual)


if __name__ == "__main__":
    unittest.main()
