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

type ProfileSnapshot = Record<string, unknown> & {
  confirm_readiness: { ready: boolean; missing: string[]; field_errors: Record<string, string[]> };
};

type ResolvedMeta = {
  version_id: string;
  effective_from: string;
  is_confirmed: boolean;
  confirmed_at: string | null;
  confirmed_role: string | null;
};

export type OrgProfileMock = {
  /** Снимок последней версии (тот же объект, что в snapshots[latest]). */
  profile: ProfileSnapshot & ResolvedMeta & {
    company_id: string;
    period: string;
    profile_unconfirmed: boolean;
    can_write: boolean;
  };
  versions: VersionRow[];
  snapshots: Record<string, ProfileSnapshot>;
};

function latestVersionRow(state: OrgProfileMock): VersionRow {
  return state.versions[state.versions.length - 1];
}

function normalizePeriod(period: string): string {
  return `${period.slice(0, 7)}-01`;
}

function resolveForPeriod(state: OrgProfileMock, periodMonth: string): ResolvedMeta & ProfileSnapshot {
  const period = normalizePeriod(periodMonth);
  let chosen: VersionRow | undefined;
  for (const row of state.versions) {
    if (row.effective_from <= period) {
      chosen = row;
    }
  }
  if (!chosen) {
    chosen = state.versions[0];
  }
  const snap = state.snapshots[chosen.version_id];
  return {
    ...snap,
    version_id: chosen.version_id,
    effective_from: chosen.effective_from,
    is_confirmed: chosen.is_confirmed,
    confirmed_at: chosen.confirmed_at,
    confirmed_role: chosen.confirmed_role,
  };
}

function buildProfileResponse(
  state: OrgProfileMock,
  companyId: string,
  period: string,
  canWrite: boolean,
): OrgProfileMock["profile"] {
  const periodNorm = normalizePeriod(period);
  const resolved = resolveForPeriod(state, periodNorm);
  const snap = state.snapshots[resolved.version_id];
  return {
    ...snap,
    company_id: companyId,
    period: periodNorm,
    version_id: resolved.version_id,
    effective_from: resolved.effective_from,
    is_confirmed: resolved.is_confirmed,
    confirmed_at: resolved.confirmed_at,
    confirmed_role: resolved.confirmed_role,
    profile_unconfirmed: !resolved.is_confirmed,
    can_write: canWrite,
    support_level: "supported",
    support_code: null,
  } as OrgProfileMock["profile"];
}

function buildLatestWriteResponse(state: OrgProfileMock, companyId: string, canWrite: boolean) {
  const latest = latestVersionRow(state);
  const snap = state.snapshots[latest.version_id];
  return {
    ...snap,
    company_id: companyId,
    period: latest.effective_from,
    version_id: latest.version_id,
    effective_from: latest.effective_from,
    is_confirmed: latest.is_confirmed,
    confirmed_at: latest.confirmed_at,
    confirmed_role: latest.confirmed_role,
    profile_unconfirmed: !latest.is_confirmed,
    can_write: canWrite,
    support_level: "supported",
    support_code: null,
  };
}

function syncProfileRef(state: OrgProfileMock, companyId: string, canWrite: boolean): void {
  const latest = buildLatestWriteResponse(state, companyId, canWrite);
  Object.assign(state.profile, latest);
}

function recomputeReadiness(snapshot: ProfileSnapshot): void {
  const missing: string[] = [];
  const profile = snapshot as Record<string, unknown>;
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
  snapshot.confirm_readiness = {
    ready: missing.length === 0,
    missing,
    field_errors: {},
  };
}

export function completeDraftProfile(state: OrgProfileMock): void {
  Object.assign(state.profile, {
    org_form: "ooo",
    tax_system: "usn",
    usn_tax_object: "income",
    vat_status: "not_applicable",
    is_new_organization: true,
    accounting_source: "onec",
    industry_sphere: "trade",
    money_channels: ["bank"],
    month_close_policy: "calendar_month_end",
    revenue_recognition_method: "accrual",
  });
  const latestId = latestVersionRow(state).version_id;
  const { is_confirmed: _ic, profile_unconfirmed: _pu, version_id: _vid, ...profileFields } =
    state.profile;
  Object.assign(state.snapshots[latestId], profileFields);
  recomputeReadiness(state.snapshots[latestId]);
  recomputeReadiness(state.profile);
}

function emptySnapshot(): ProfileSnapshot {
  return {
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
}

export function draftOrgProfile(companyId: string, canWrite = true): OrgProfileMock {
  const versionId = "v-draft-1";
  const effectiveFrom = "2026-03-01";
  const snapshots: Record<string, ProfileSnapshot> = {
    [versionId]: emptySnapshot(),
  };
  recomputeReadiness(snapshots[versionId]);
  const versions: VersionRow[] = [
    {
      version_id: versionId,
      effective_from: effectiveFrom,
      is_confirmed: false,
      confirmed_at: null,
      confirmed_role: null,
      change_reason: null,
      created_at: "2026-03-01T00:00:00Z",
    },
  ];
  const profile = buildLatestWriteResponse(
    { versions, snapshots, profile: {} as OrgProfileMock["profile"] },
    companyId,
    canWrite,
  ) as OrgProfileMock["profile"];
  return { profile, versions, snapshots };
}

export function confirmLatestInMock(state: OrgProfileMock): void {
  const latest = latestVersionRow(state);
  latest.is_confirmed = true;
  latest.confirmed_at = "2026-03-10T00:00:00Z";
  latest.confirmed_role = "owner";
  state.profile.is_confirmed = true;
  state.profile.confirmed_at = latest.confirmed_at;
  state.profile.confirmed_role = "owner";
  state.profile.profile_unconfirmed = false;
}

export async function installOrgProfileMock(page: Page, companyId: string, state: OrgProfileMock) {
  const canWrite = state.profile.can_write;
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
        body: JSON.stringify(buildProfileResponse(state, companyId, period, canWrite)),
      });
      return;
    }
    if (request.method() === "PATCH" && url.includes("/organization-profile/draft")) {
      const patch = request.postDataJSON() as Record<string, unknown>;
      const latest = latestVersionRow(state);
      Object.assign(state.snapshots[latest.version_id], patch);
      recomputeReadiness(state.snapshots[latest.version_id]);
      syncProfileRef(state, companyId, canWrite);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(buildLatestWriteResponse(state, companyId, canWrite)),
      });
      return;
    }
    if (request.method() === "POST" && url.includes("/organization-profile/versions") && !url.includes("/confirm")) {
      const body = request.postDataJSON() as Record<string, unknown>;
      const versionId = `v-${state.versions.length + 1}`;
      const effectiveFrom = String(body.effective_from);
      const snap: ProfileSnapshot = {
        ...emptySnapshot(),
        ...body,
        confirm_readiness: { ready: false, missing: [], field_errors: {} },
      };
      delete (snap as Record<string, unknown>).effective_from;
      delete (snap as Record<string, unknown>).change_reason;
      delete (snap as Record<string, unknown>).version_id;
      recomputeReadiness(snap);
      state.snapshots[versionId] = snap;
      state.versions.push({
        version_id: versionId,
        effective_from: effectiveFrom,
        is_confirmed: false,
        confirmed_at: null,
        confirmed_role: null,
        change_reason: String(body.change_reason ?? ""),
        created_at: "2026-03-02T00:00:00Z",
      });
      syncProfileRef(state, companyId, canWrite);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(buildLatestWriteResponse(state, companyId, canWrite)),
      });
      return;
    }
    if (request.method() === "POST" && url.includes("/confirm")) {
      const match = url.match(/\/versions\/([^/]+)\/confirm/);
      const versionId = match?.[1];
      const latest = latestVersionRow(state);
      if (!versionId || versionId !== latest.version_id) {
        await route.fulfill({
          status: 400,
          contentType: "application/json",
          body: JSON.stringify({
            code: "not_latest_version",
            message: "Подтвердить можно только последнюю версию",
          }),
        });
        return;
      }
      latest.is_confirmed = true;
      latest.confirmed_at = "2026-03-10T00:00:00Z";
      latest.confirmed_role = "owner";
      syncProfileRef(state, companyId, canWrite);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(buildLatestWriteResponse(state, companyId, canWrite)),
      });
      return;
    }
    await route.continue();
  };

  const profilePath = `/api/v1/companies/${companyId}/organization-profile`;
  await page.context().route(
    (url) => {
      const path = url.pathname;
      return path === profilePath || path.startsWith(`${profilePath}/`);
    },
    handler,
  );
  await page.route("**/api/v1/tax-norms/current**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        status: "ok",
        needs_review_banner: false,
        values: { usn_vat_exemption_threshold_rub: "20000000.00" },
      }),
    });
  });
}

export function resolvedProfileForPeriod(state: OrgProfileMock, period: string): ResolvedMeta {
  const resolved = resolveForPeriod(state, period);
  return {
    version_id: resolved.version_id,
    effective_from: resolved.effective_from,
    is_confirmed: resolved.is_confirmed,
    confirmed_at: resolved.confirmed_at,
    confirmed_role: resolved.confirmed_role,
    confirm_readiness: resolved.confirm_readiness,
  };
}
