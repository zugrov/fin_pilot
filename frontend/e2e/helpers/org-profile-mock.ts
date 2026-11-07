import type { Page, Route } from "@playwright/test";

type VersionRow = {
  version_id: string;
  effective_from: string;
  is_confirmed: boolean;
  confirmed_at: string | null;
  confirmed_role: string | null;
  change_reason: string | null;
  created_at: string | null;
};

type ProfileState = Record<string, unknown> & {
  version_id: string;
  effective_from: string;
  is_confirmed: boolean;
  profile_unconfirmed: boolean;
  can_write: boolean;
  confirm_readiness: { ready: boolean; missing: string[]; field_errors: Record<string, string[]> };
};

export type OrgProfileMock = {
  profile: ProfileState;
  versions: VersionRow[];
};

function cloneProfile(state: OrgProfileMock, period: string): ProfileState {
  return { ...state.profile, period } as ProfileState;
}

function recomputeReadiness(profile: ProfileState): void {
  const missing: string[] = [];
  if (profile.org_form === "unspecified") missing.push("org_form");
  if (profile.tax_system === "unspecified") missing.push("tax_system");
  if (profile.tax_system === "usn" && profile.usn_tax_object === "unspecified") {
    missing.push("usn_tax_object");
  }
  if (profile.vat_status === "unknown" || profile.vat_status === "unspecified") {
    missing.push("vat_status");
  }
  if (profile.accounting_source === "unspecified") missing.push("accounting_source");
  const channels = profile.money_channels as string[];
  const usable = (channels ?? []).filter((c) => c !== "unspecified");
  if (!usable.length) {
    missing.push("money_channels");
  }
  if (profile.month_close_policy === "unknown") missing.push("month_close_policy");
  if (profile.revenue_recognition_method === "unknown") {
    missing.push("revenue_recognition_method");
  }
  if (profile.is_new_organization !== true) {
    if (profile.prior_year_revenue_band === "unknown") {
      missing.push("prior_year_revenue_band");
    }
  }
  profile.confirm_readiness = {
    ready: missing.length === 0,
    missing,
    field_errors: {},
  };
  profile.profile_unconfirmed = !profile.is_confirmed;
}

export function draftOrgProfile(companyId: string, canWrite = true): OrgProfileMock {
  const versionId = "v-draft-1";
  const profile: ProfileState = {
    company_id: companyId,
    period: "2026-03-01",
    version_id: versionId,
    effective_from: "2026-03-01",
    is_confirmed: false,
    confirmed_at: null,
    confirmed_role: null,
    profile_unconfirmed: true,
    can_write: canWrite,
    support_level: "supported",
    support_code: null,
    confirm_readiness: { ready: false, missing: ["org_form", "tax_system"], field_errors: {} },
    org_form: "unspecified",
    tax_system: "unspecified",
    usn_tax_object: "unspecified",
    vat_status: "unknown",
    vat_regime_detail: null,
    vat_default_rate: null,
    prices_include_vat: "unknown",
    vat_exemption_article_145: null,
    is_new_organization: true,
    prior_year_revenue_band: "unknown",
    accounting_source: "unspecified",
    industry_sphere: "unspecified",
    money_channels: ["unspecified"],
    month_close_policy: "unknown",
    revenue_recognition_method: "unknown",
  };
  recomputeReadiness(profile);
  return {
    profile,
    versions: [
      {
        version_id: versionId,
        effective_from: "2026-03-01",
        is_confirmed: false,
        confirmed_at: null,
        confirmed_role: null,
        change_reason: null,
        created_at: "2026-03-01T00:00:00Z",
      },
    ],
  };
}

export async function installOrgProfileMock(page: Page, companyId: string, state: OrgProfileMock) {
  const handler = async (route: Route) => {
    const request = route.request();
    const url = request.url();
    if (request.method() === "GET" && url.includes("/organization-profile/versions")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ company_id: companyId, versions: state.versions }),
      });
      return;
    }
    if (request.method() === "GET" && url.includes("/organization-profile")) {
      const period = new URL(url).searchParams.get("period") ?? state.profile.period;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(cloneProfile(state, `${period.slice(0, 7)}-01`)),
      });
      return;
    }
    if (request.method() === "PATCH" && url.includes("/organization-profile/draft")) {
      const patch = request.postDataJSON() as Record<string, unknown>;
      Object.assign(state.profile, patch);
      recomputeReadiness(state.profile);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(state.profile),
      });
      return;
    }
    if (request.method() === "POST" && url.includes("/organization-profile/versions") && !url.includes("/confirm")) {
      const body = request.postDataJSON() as Record<string, unknown>;
      const versionId = `v-${state.versions.length + 1}`;
      Object.assign(state.profile, body, {
        version_id: versionId,
        effective_from: body.effective_from,
        period: body.effective_from,
        is_confirmed: false,
        confirmed_at: null,
        confirmed_role: null,
      });
      state.versions.push({
        version_id: versionId,
        effective_from: String(body.effective_from),
        is_confirmed: false,
        confirmed_at: null,
        confirmed_role: null,
        change_reason: String(body.change_reason ?? ""),
        created_at: "2026-03-02T00:00:00Z",
      });
      recomputeReadiness(state.profile);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(state.profile),
      });
      return;
    }
    if (request.method() === "POST" && url.includes("/confirm")) {
      state.profile.is_confirmed = true;
      state.profile.confirmed_at = "2026-03-10T00:00:00Z";
      state.profile.confirmed_role = "owner";
      state.versions[0].is_confirmed = true;
      state.versions[0].confirmed_at = state.profile.confirmed_at;
      recomputeReadiness(state.profile);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(state.profile),
      });
      return;
    }
    await route.continue();
  };

  await page.route(`**/api/v1/companies/${companyId}/organization-profile**`, handler);
  await page.route("**/api/v1/tax-norms/current**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "ok",
        needs_review_banner: false,
        values: { usn_vat_exemption_threshold_rub: "60000000.00" },
      }),
    });
  });
}
