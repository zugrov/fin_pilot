import { describe, expect, it } from "vitest";

import type { OrganizationProfile } from "../api";
import { buildVersionCreateBody } from "./orgProfileVersionSnapshot";
import { confirmedFutureVersion, versionCreateSnapshotSource } from "./orgProfileVersionCreate";

function profile(overrides: Partial<OrganizationProfile>): OrganizationProfile {
  return {
    company_id: "c1",
    period: "2026-07-01",
    version_id: "v-future",
    effective_from: "2026-07-01",
    is_confirmed: true,
    confirmed_at: "2026-03-01T00:00:00Z",
    confirmed_role: "owner",
    profile_unconfirmed: false,
    can_write: true,
    support_level: "supported",
    support_code: null,
    confirm_readiness: { ready: true, missing: [], field_errors: {} },
    org_form: "ooo",
    tax_system: "osno",
    usn_tax_object: "unspecified",
    vat_status: "vat_payer",
    vat_regime_detail: "with_deductions",
    vat_default_rate: "22",
    prices_include_vat: "yes",
    vat_exemption_article_145: false,
    is_new_organization: false,
    prior_year_revenue_band: "unknown",
    accounting_source: "onec",
    industry_sphere: "trade",
    money_channels: ["bank"],
    month_close_policy: "calendar_month_end",
    revenue_recognition_method: "accrual",
    ...overrides,
  };
}

describe("orgProfileVersionCreate", () => {
  it("снимок из wizard profile, а не из карточки", () => {
    const card = profile({ tax_system: "usn", version_id: "v-card", period: "2026-03-01" });
    const wizard = profile({ tax_system: "osno", version_id: "v-future" });
    const source = versionCreateSnapshotSource(wizard, card);
    const body = buildVersionCreateBody(source!, "2026-10-01", "ещё одно изменение");
    expect(body.tax_system).toBe("osno");
  });

  it("находит подтверждённую будущую версию", () => {
    const versions = [
      { version_id: "v1", effective_from: "2026-01-01", is_confirmed: true },
      { version_id: "v2", effective_from: "2026-07-01", is_confirmed: true },
    ];
    expect(confirmedFutureVersion(versions, "2026-03-01")?.version_id).toBe("v2");
  });
});
