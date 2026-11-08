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
            patch.object(mod, "create_company", return_value="company-special"),
            patch.object(mod, "activate_company_slot", return_value=True),
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
            mod.run_special_rates_company(client, "tenant", billing, "", report)
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


if __name__ == "__main__":
    unittest.main()
