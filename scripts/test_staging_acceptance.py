"""Локальные тесты логики scripts/staging_acceptance.py (без HTTP к стенду)."""

from __future__ import annotations

import importlib.util
import sys
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
        with patch.object(self.mod, "REPORT_PATH", Path("/tmp/acceptance-report-test.md")):
            self.mod.write_report(report, "secret@example.com", "b@example.com")
            text = Path("/tmp/acceptance-report-test.md").read_text(encoding="utf-8")
        self.assertNotIn("secret@", text)
        self.assertIn("***@", text)


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
