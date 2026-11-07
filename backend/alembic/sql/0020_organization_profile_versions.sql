-- P1b: версии профиля организации (append-only, подтверждение owner/accountant — в сервисе).

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
    UNIQUE (company_id, effective_from)
);

CREATE INDEX organization_profile_versions_tenant_company_idx
  ON organization_profile_versions (tenant_id, company_id);

CREATE INDEX organization_profile_versions_company_effective_idx
  ON organization_profile_versions (company_id, effective_from DESC);

GRANT SELECT, INSERT, UPDATE ON organization_profile_versions TO finpilot_app;
GRANT SELECT, INSERT, UPDATE ON organization_profile_versions TO finpilot_worker;

-- Стартовая неподтверждённая версия для каждой организации (защита пилота §2 плана).
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
