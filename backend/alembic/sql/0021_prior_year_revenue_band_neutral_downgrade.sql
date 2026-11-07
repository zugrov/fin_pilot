-- Откат: прежние коды диапазона выручки.

ALTER TABLE organization_profile_versions DISABLE TRIGGER organization_profile_versions_guard_tr;

ALTER TABLE organization_profile_versions
  DROP CONSTRAINT organization_profile_versions_prior_band_ck;

UPDATE organization_profile_versions
SET prior_year_revenue_band = 'under_20m'
WHERE prior_year_revenue_band = 'under_exemption_threshold';

UPDATE organization_profile_versions
SET prior_year_revenue_band = 'from_20m_to_272_5m'
WHERE prior_year_revenue_band = 'from_threshold_to_cap_5';

UPDATE organization_profile_versions
SET prior_year_revenue_band = 'from_272_5m_to_490_5m'
WHERE prior_year_revenue_band = 'from_cap_5_to_cap_7';

UPDATE organization_profile_versions
SET prior_year_revenue_band = 'over_490_5m'
WHERE prior_year_revenue_band = 'over_cap_7';

ALTER TABLE organization_profile_versions
  ADD CONSTRAINT organization_profile_versions_prior_band_ck
    CHECK (
      prior_year_revenue_band IN (
        'unknown', 'unspecified',
        'under_20m',
        'from_20m_to_272_5m',
        'from_272_5m_to_490_5m',
        'over_490_5m'
      )
    );

ALTER TABLE organization_profile_versions ENABLE TRIGGER organization_profile_versions_guard_tr;
