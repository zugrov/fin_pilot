-- P1b: версии профиля организации; черновик редактируем, подтверждённая — неизменяема.

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '120s';

CREATE TABLE organization_profile_versions (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants (id),
  company_id uuid NOT NULL REFERENCES companies (id),
  effective_from date NOT NULL,
  org_form text NOT NULL DEFAULT 'unspecified',
  tax_system text NOT NULL DEFAULT 'unspecified',
  usn_tax_object text NOT NULL DEFAULT 'unspecified',
  vat_status text NOT NULL DEFAULT 'unknown',
  vat_regime_detail text,
  vat_default_rate text,
  prices_include_vat text NOT NULL DEFAULT 'unknown',
  vat_exemption_article_145 boolean,
  is_new_organization boolean,
  revenue_recognition_method text NOT NULL DEFAULT 'unknown',
  accounting_source text NOT NULL DEFAULT 'unspecified',
  industry_sphere text NOT NULL DEFAULT 'unspecified',
  money_channels jsonb NOT NULL DEFAULT '["unspecified"]'::jsonb,
  prior_year_revenue_band text NOT NULL DEFAULT 'unknown',
  month_close_policy text NOT NULL DEFAULT 'unknown',
  created_at timestamptz NOT NULL DEFAULT now(),
  created_by uuid REFERENCES users (id),
  change_reason text,
  confirmed_at timestamptz,
  confirmed_by uuid REFERENCES users (id),
  confirmed_role text,
  CONSTRAINT organization_profile_versions_effective_from_month_ck
    CHECK (effective_from = date_trunc('month', effective_from::timestamp)::date),
  CONSTRAINT organization_profile_versions_confirm_pair_ck
    CHECK (
      (confirmed_at IS NULL AND confirmed_by IS NULL AND confirmed_role IS NULL)
      OR (
        confirmed_at IS NOT NULL
        AND confirmed_by IS NOT NULL
        AND confirmed_role IS NOT NULL
      )
    ),
  CONSTRAINT organization_profile_versions_confirmed_role_ck
    CHECK (confirmed_role IS NULL OR confirmed_role IN ('owner', 'accountant')),
  CONSTRAINT organization_profile_versions_company_effective_uq
    UNIQUE (company_id, effective_from),
  CONSTRAINT organization_profile_versions_org_form_ck
    CHECK (org_form IN ('unspecified', 'ip', 'ooo', 'ao')),
  CONSTRAINT organization_profile_versions_tax_system_ck
    CHECK (
      tax_system IN (
        'unspecified', 'usn', 'osno', 'ausn', 'psn', 'eshn', 'self_employed'
      )
    ),
  CONSTRAINT organization_profile_versions_usn_tax_object_ck
    CHECK (usn_tax_object IN ('unspecified', 'income', 'income_minus_expense')),
  CONSTRAINT organization_profile_versions_vat_status_ck
    CHECK (
      vat_status IN (
        'unknown', 'vat_payer', 'special_rates_5_7', 'exemption', 'not_applicable'
      )
    ),
  CONSTRAINT organization_profile_versions_vat_regime_detail_ck
    CHECK (
      vat_regime_detail IS NULL
      OR vat_regime_detail IN (
        'unspecified', 'with_deductions', 'special_without_deductions'
      )
    ),
  CONSTRAINT organization_profile_versions_vat_default_rate_ck
    CHECK (
      vat_default_rate IS NULL
      OR vat_default_rate IN ('unspecified', '22', '10', '0')
    ),
  CONSTRAINT organization_profile_versions_prices_include_vat_ck
    CHECK (prices_include_vat IN ('unknown', 'yes', 'no')),
  CONSTRAINT organization_profile_versions_revenue_method_ck
    CHECK (revenue_recognition_method IN ('unknown', 'accrual', 'cash', 'other')),
  CONSTRAINT organization_profile_versions_accounting_source_ck
    CHECK (accounting_source IN ('unspecified', 'onec', 'cloud', 'book_csv')),
  CONSTRAINT organization_profile_versions_industry_sphere_ck
    CHECK (industry_sphere IN ('unspecified', 'trade', 'services', 'production', 'mixed')),
  CONSTRAINT organization_profile_versions_prior_band_ck
    CHECK (
      prior_year_revenue_band IN (
        'unknown', 'unspecified', 'under_20m',
        'from_20m_to_272_5m', 'from_272_5m_to_490_5m', 'over_490_5m'
      )
    ),
  CONSTRAINT organization_profile_versions_month_close_ck
    CHECK (month_close_policy IN ('unknown', 'calendar_month_end', 'manual', 'other'))
);

CREATE OR REPLACE FUNCTION organization_profile_versions_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF TG_OP = 'DELETE' THEN
    RAISE EXCEPTION 'organization_profile_versions_delete_forbidden';
  END IF;

  IF TG_OP = 'UPDATE' THEN
    IF OLD.confirmed_at IS NOT NULL THEN
      RAISE EXCEPTION 'organization_profile_confirmed_immutable';
    END IF;

    IF NEW.confirmed_at IS NOT NULL THEN
      IF NEW.org_form IS DISTINCT FROM OLD.org_form
        OR NEW.tax_system IS DISTINCT FROM OLD.tax_system
        OR NEW.usn_tax_object IS DISTINCT FROM OLD.usn_tax_object
        OR NEW.vat_status IS DISTINCT FROM OLD.vat_status
        OR NEW.vat_regime_detail IS DISTINCT FROM OLD.vat_regime_detail
        OR NEW.vat_default_rate IS DISTINCT FROM OLD.vat_default_rate
        OR NEW.prices_include_vat IS DISTINCT FROM OLD.prices_include_vat
        OR NEW.vat_exemption_article_145 IS DISTINCT FROM OLD.vat_exemption_article_145
        OR NEW.is_new_organization IS DISTINCT FROM OLD.is_new_organization
        OR NEW.revenue_recognition_method IS DISTINCT FROM OLD.revenue_recognition_method
        OR NEW.accounting_source IS DISTINCT FROM OLD.accounting_source
        OR NEW.industry_sphere IS DISTINCT FROM OLD.industry_sphere
        OR NEW.money_channels IS DISTINCT FROM OLD.money_channels
        OR NEW.prior_year_revenue_band IS DISTINCT FROM OLD.prior_year_revenue_band
        OR NEW.month_close_policy IS DISTINCT FROM OLD.month_close_policy
        OR NEW.effective_from IS DISTINCT FROM OLD.effective_from
        OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
        OR NEW.company_id IS DISTINCT FROM OLD.company_id
      THEN
        RAISE EXCEPTION 'confirm_must_not_change_profile_fields';
      END IF;
    ELSE
      IF NEW.confirmed_by IS DISTINCT FROM OLD.confirmed_by
        OR NEW.confirmed_role IS DISTINCT FROM OLD.confirmed_role
      THEN
        RAISE EXCEPTION 'confirmation_fields_without_confirmed_at';
      END IF;
    END IF;
  END IF;

  RETURN NEW;
END;
$$;

CREATE TRIGGER organization_profile_versions_guard_tr
  BEFORE UPDATE OR DELETE ON organization_profile_versions
  FOR EACH ROW
  EXECUTE FUNCTION organization_profile_versions_guard();

CREATE INDEX organization_profile_versions_tenant_company_idx
  ON organization_profile_versions (tenant_id, company_id);

CREATE INDEX organization_profile_versions_company_effective_idx
  ON organization_profile_versions (company_id, effective_from DESC);

REVOKE DELETE ON organization_profile_versions FROM finpilot_app, finpilot_worker;
GRANT SELECT, INSERT, UPDATE ON organization_profile_versions TO finpilot_app;
GRANT SELECT, INSERT, UPDATE ON organization_profile_versions TO finpilot_worker;

INSERT INTO organization_profile_versions (
  id,
  tenant_id,
  company_id,
  effective_from,
  change_reason,
  created_by
)
SELECT
  gen_random_uuid(),
  c.tenant_id,
  c.id,
  (date_trunc('month', c.created_at AT TIME ZONE 'UTC'))::date,
  'migration_p1b_bootstrap',
  NULL
FROM companies c;
