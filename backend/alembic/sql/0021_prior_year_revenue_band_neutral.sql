-- P2c: нейтральные коды диапазона выручки (без привязки к конкретным суммам в имени enum).

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE organization_profile_versions DISABLE TRIGGER organization_profile_versions_guard_tr;

ALTER TABLE organization_profile_versions
  DROP CONSTRAINT organization_profile_versions_prior_band_ck;

UPDATE organization_profile_versions
SET prior_year_revenue_band = 'under_exemption_threshold'
WHERE prior_year_revenue_band = 'under_20m';

UPDATE organization_profile_versions
SET prior_year_revenue_band = 'from_threshold_to_cap_5'
WHERE prior_year_revenue_band = 'from_20m_to_272_5m';

UPDATE organization_profile_versions
SET prior_year_revenue_band = 'from_cap_5_to_cap_7'
WHERE prior_year_revenue_band = 'from_272_5m_to_490_5m';

UPDATE organization_profile_versions
SET prior_year_revenue_band = 'over_cap_7'
WHERE prior_year_revenue_band = 'over_490_5m';

ALTER TABLE organization_profile_versions
  ADD CONSTRAINT organization_profile_versions_prior_band_ck
    CHECK (
      prior_year_revenue_band IN (
        'unknown', 'unspecified',
        'under_exemption_threshold',
        'from_threshold_to_cap_5',
        'from_cap_5_to_cap_7',
        'over_cap_7'
      )
    );

ALTER TABLE organization_profile_versions ENABLE TRIGGER organization_profile_versions_guard_tr;
