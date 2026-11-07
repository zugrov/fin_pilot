import { describe, expect, it } from "vitest";

import type { OrganizationProfile } from "../api";
import { buildVersionCreateBody } from "./orgProfileVersionSnapshot";
import { versionCreateSnapshotSource } from "./orgProfileVersionCreate";
import {
  canConfirmOrganizationProfile,
  confirmTargetVersionId,
  latestProfileVersion,
  wizardProfilePeriod,
  wizardWriteActionsVisible,
} from "./orgProfileWizardPlan";

/** Сценарные тесты P3b (vitest, без DOM) — модель потоков мастера. */

function readyProfile(): OrganizationProfile {
  return {
    company_id: "c1",
    period: "2026-03-01",
    version_id: "v-draft",
    effective_from: "2026-03-01",
    is_confirmed: false,
    confirmed_at: null,
    confirmed_role: null,
    profile_unconfirmed: true,
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
  };
}

describe("сценарий a: первичное подтверждение", () => {
  it("после заполнения и «Сохранить и проверить» можно подтвердить", () => {
    const draft = readyProfile();
    const locals = {
      month: draft.month_close_policy,
      revenue: draft.revenue_recognition_method,
    };
    expect(draft.confirm_readiness.ready).toBe(true);
    expect(canConfirmOrganizationProfile(draft, locals.month, locals.revenue)).toBe(true);
    const confirmed = { ...draft, is_confirmed: true, confirmed_at: "2026-03-10T00:00:00Z" };
    expect(confirmed.is_confirmed).toBe(true);
  });
});

describe("сценарий b: новая версия с будущей даты", () => {
  it("мастер на новом version_id и периоде", () => {
    const cardProfile = readyProfile();
    const confirmedCard = {
      ...cardProfile,
      is_confirmed: true,
      version_id: "v1",
      tax_system: "usn",
    };
    const versions = [
      { version_id: "v1", effective_from: "2026-01-01", is_confirmed: true },
      { version_id: "v2", effective_from: "2026-07-01", is_confirmed: false },
    ];
    const latest = latestProfileVersion(versions);
    const now = new Date("2026-03-15T12:00:00Z");
    const wizardPeriod = wizardProfilePeriod("Europe/Moscow", latest?.effective_from, now);
    expect(wizardPeriod).toBe("2026-07-01");
    const newDraft: OrganizationProfile = {
      ...confirmedCard,
      version_id: "v2",
      effective_from: "2026-07-01",
      is_confirmed: false,
      tax_system: "osno",
      period: "2026-07-01",
      profile_unconfirmed: true,
    };
    expect(newDraft.tax_system).toBe("osno");
    expect(confirmedCard.tax_system).toBe("usn");
    expect(confirmTargetVersionId(latest, newDraft.version_id)).toBe("v2");
    const body = buildVersionCreateBody(
      versionCreateSnapshotSource(newDraft, confirmedCard)!,
      "2026-10-01",
      "ещё одно изменение",
    );
    expect(body.tax_system).toBe("osno");
    expect(body.effective_from).toBe("2026-10-01");
  });
});

describe("сценарий c: viewer", () => {
  it("без кнопок записи", () => {
    const viewerProfile = readyProfile();
    viewerProfile.can_write = false;
    expect(wizardWriteActionsVisible(viewerProfile.can_write)).toBe(false);
  });
});
