import { describe, expect, it } from "vitest";

import type { OrganizationProfile } from "../api";
import {
  canConfirmOrganizationProfile,
  confirmTargetVersionId,
  currentPeriodMonth,
  isFutureUnconfirmedDraft,
  latestProfileVersion,
  shouldShowWizard,
  step6FieldsMatchSaved,
  wizardProfilePeriod,
  wizardWriteActionsVisible,
} from "./orgProfileWizardPlan";

function profile(overrides: Partial<OrganizationProfile> = {}): OrganizationProfile {
  return {
    company_id: "c1",
    period: "2026-03-01",
    version_id: "draft-1",
    effective_from: "2026-03-01",
    is_confirmed: false,
    confirmed_at: null,
    confirmed_role: null,
    profile_unconfirmed: true,
    can_write: true,
    support_level: "supported",
    support_code: null,
    confirm_readiness: { ready: false, missing: ["org_form"], field_errors: {} },
    org_form: "unspecified",
    tax_system: "unspecified",
    usn_tax_object: "unspecified",
    vat_status: "unknown",
    vat_regime_detail: null,
    vat_default_rate: null,
    prices_include_vat: "unknown",
    vat_exemption_article_145: null,
    is_new_organization: null,
    prior_year_revenue_band: "unknown",
    accounting_source: "unspecified",
    industry_sphere: "unspecified",
    money_channels: ["unspecified"],
    month_close_policy: "unknown",
    revenue_recognition_method: "unknown",
    ...overrides,
  };
}

describe("orgProfileWizardPlan", () => {
  it("wizardProfilePeriod берёт max текущего месяца и effective_from", () => {
    const now = new Date("2026-03-15T12:00:00Z");
    expect(currentPeriodMonth("Europe/Moscow", now)).toBe("2026-03-01");
    expect(wizardProfilePeriod("Europe/Moscow", "2026-07-01", now)).toBe("2026-07-01");
    expect(wizardProfilePeriod("Europe/Moscow", "2026-01-01", now)).toBe("2026-03-01");
  });

  it("confirm использует id последней версии", () => {
    const versions = [
      { version_id: "v1", effective_from: "2026-01-01", is_confirmed: true },
      { version_id: "v2", effective_from: "2026-07-01", is_confirmed: false },
    ];
    const latest = latestProfileVersion(versions);
    expect(confirmTargetVersionId(latest, "stale")).toBe("v2");
  });

  it("будущий черновик", () => {
    const latest = { version_id: "v2", effective_from: "2026-07-01", is_confirmed: false };
    expect(isFutureUnconfirmedDraft(latest, "2026-03-01")).toBe(true);
    expect(shouldShowWizard(latest)).toBe(true);
  });

  it("confirm доступен при ready и совпадении шага 6", () => {
    const ready = profile({
      confirm_readiness: { ready: true, missing: [], field_errors: {} },
      month_close_policy: "calendar_month_end",
      revenue_recognition_method: "accrual",
    });
    expect(
      canConfirmOrganizationProfile(ready, "calendar_month_end", "accrual"),
    ).toBe(true);
    expect(step6FieldsMatchSaved("manual", "accrual", ready)).toBe(false);
    expect(
      canConfirmOrganizationProfile(ready, "manual", "accrual"),
    ).toBe(false);
  });

  it("viewer без кнопок записи", () => {
    expect(wizardWriteActionsVisible(false)).toBe(false);
    expect(wizardWriteActionsVisible(true)).toBe(true);
  });
});
