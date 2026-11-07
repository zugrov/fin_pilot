import type { OrganizationProfile } from "../api";

/** Полный снимок для POST organization-profile/versions из текущего профиля. */
export function buildVersionCreateBody(
  profile: OrganizationProfile,
  effectiveFrom: string,
  changeReason: string,
): Record<string, unknown> {
  return {
    effective_from: effectiveFrom,
    change_reason: changeReason.trim(),
    org_form: profile.org_form,
    tax_system: profile.tax_system,
    usn_tax_object: profile.usn_tax_object,
    vat_status: profile.vat_status,
    vat_regime_detail: profile.vat_regime_detail,
    vat_default_rate: profile.vat_default_rate,
    prices_include_vat: profile.prices_include_vat,
    vat_exemption_article_145: profile.vat_exemption_article_145,
    is_new_organization: profile.is_new_organization,
    revenue_recognition_method: profile.revenue_recognition_method,
    accounting_source: profile.accounting_source,
    industry_sphere: profile.industry_sphere,
    money_channels: profile.money_channels ?? ["unspecified"],
    prior_year_revenue_band: profile.prior_year_revenue_band,
    month_close_policy: profile.month_close_policy,
  };
}
