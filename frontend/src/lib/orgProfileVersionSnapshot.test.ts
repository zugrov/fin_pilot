import { describe, expect, it } from "vitest";

import type { OrganizationProfile } from "../api";
import { buildVersionCreateBody } from "./orgProfileVersionSnapshot";

function sampleProfile(overrides: Partial<OrganizationProfile> = {}): OrganizationProfile {
  return {
    company_id: "c1",
    period: "2026-03-01",
    version_id: "v1",
    effective_from: "2026-01-01",
    is_confirmed: true,
    confirmed_at: "2026-02-01T00:00:00Z",
    confirmed_role: "owner",
    profile_unconfirmed: false,
    can_write: true,
    support_level: "supported",
    support_code: null,
    confirm_readiness: { ready: true, missing: [], field_errors: {} },
    org_form: "ooo",
    tax_system: "usn",
    usn_tax_object: "income",
    vat_status: "not_applicable",
    vat_regime_detail: null,
    vat_default_rate: null,
    prices_include_vat: "unknown",
    vat_exemption_article_145: false,
    is_new_organization: true,
    prior_year_revenue_band: "unknown",
    accounting_source: "onec",
    industry_sphere: "trade",
    money_channels: ["bank"],
    month_close_policy: "calendar_month_end",
    revenue_recognition_method: "accrual",
    ...overrides,
  };
}

describe("orgProfileVersionSnapshot", () => {
  it("формирует полный снимок для POST versions", () => {
    const body = buildVersionCreateBody(sampleProfile(), "2026-04-01", "смена режима");
    expect(body.effective_from).toBe("2026-04-01");
    expect(body.change_reason).toBe("смена режима");
    expect(body.tax_system).toBe("usn");
    expect(body.money_channels).toEqual(["bank"]);
    expect(body.accounting_source).toBe("onec");
  });
});
