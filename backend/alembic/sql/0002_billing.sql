CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE SEQUENCE invoice_number_seq;

CREATE TABLE tariff_versions (
  id uuid PRIMARY KEY,
  code text NOT NULL,
  version integer NOT NULL,
  currency text NOT NULL,
  monthly_first_company_price numeric(20, 2) NOT NULL,
  monthly_additional_price numeric(20, 2) NOT NULL,
  valid_from timestamptz NOT NULL,
  valid_to timestamptz,
  status text NOT NULL,
  tax_config_version text,
  created_at timestamptz NOT NULL
);

CREATE TABLE annual_offer_versions (
  id uuid PRIMARY KEY,
  tariff_version_id uuid NOT NULL REFERENCES tariff_versions (id),
  discount_percent numeric(12, 6) NOT NULL,
  status text NOT NULL,
  approved_by text NOT NULL,
  approved_at timestamptz NOT NULL,
  approval_source text NOT NULL,
  offer_terms_version text NOT NULL,
  valid_from timestamptz NOT NULL,
  valid_to timestamptz,
  created_at timestamptz NOT NULL
);

CREATE TABLE billing_accounts (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL UNIQUE REFERENCES tenants (id),
  payer_type text,
  payer_name text,
  inn text,
  billing_email text,
  offer_version text,
  offer_accepted_at timestamptz,
  consent_versions jsonb
);

CREATE TABLE subscriptions (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL UNIQUE REFERENCES tenants (id),
  tariff_version_id uuid NOT NULL REFERENCES tariff_versions (id),
  status text NOT NULL DEFAULT 'awaiting_payment',
  company_limit integer NOT NULL DEFAULT 0,
  current_interval text,
  scheduled_interval text,
  paid_through timestamptz,
  billing_anchor timestamptz,
  timezone text NOT NULL DEFAULT 'Europe/Moscow',
  auto_renew boolean NOT NULL DEFAULT false,
  scheduled_company_limit integer,
  scheduled_keep_company_ids jsonb,
  is_renewal_cancelled boolean NOT NULL DEFAULT false,
  revision integer NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CONSTRAINT subscriptions_limit_ck CHECK (company_limit >= 0),
  CONSTRAINT subscriptions_autorenew_ck CHECK (auto_renew = false)
);

CREATE TABLE billing_periods (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  subscription_id uuid NOT NULL REFERENCES subscriptions (id),
  start_at timestamptz NOT NULL,
  end_at timestamptz NOT NULL,
  interval text NOT NULL,
  company_limit integer NOT NULL,
  monthly_base_snapshot numeric(20, 2) NOT NULL,
  discount_percent numeric(12, 6) NOT NULL,
  annual_offer_version_id uuid,
  paid_amount numeric(20, 2) NOT NULL,
  status text NOT NULL,
  activation_invoice_id uuid,
  created_at timestamptz NOT NULL,
  CONSTRAINT billing_periods_bounds_ck CHECK (start_at < end_at)
);

CREATE TABLE company_entitlements (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  subscription_id uuid NOT NULL REFERENCES subscriptions (id),
  company_id uuid NOT NULL REFERENCES companies (id),
  active_from timestamptz NOT NULL,
  active_until timestamptz NOT NULL,
  status text NOT NULL,
  period_id uuid
);

CREATE TABLE billing_quotes (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  subscription_id uuid NOT NULL REFERENCES subscriptions (id),
  kind text NOT NULL,
  interval text NOT NULL,
  as_of timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  expected_revision integer NOT NULL,
  base_company_limit integer NOT NULL,
  target_company_limit integer NOT NULL,
  list_amount numeric(20, 2) NOT NULL,
  discount_amount numeric(20, 2) NOT NULL,
  payable_amount numeric(20, 2) NOT NULL,
  discount_percent numeric(12, 6) NOT NULL,
  offer_version_id uuid,
  period_start timestamptz,
  period_end timestamptz,
  calculation_json jsonb NOT NULL,
  status text NOT NULL DEFAULT 'open',
  created_at timestamptz NOT NULL
);

CREATE TABLE invoices (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  subscription_id uuid NOT NULL REFERENCES subscriptions (id),
  quote_id uuid NOT NULL REFERENCES billing_quotes (id),
  kind text NOT NULL,
  status text NOT NULL,
  number text NOT NULL UNIQUE,
  currency text NOT NULL,
  list_amount numeric(20, 2) NOT NULL,
  discount_amount numeric(20, 2) NOT NULL,
  payable_amount numeric(20, 2) NOT NULL,
  pricing_snapshot jsonb NOT NULL,
  billing_interval text NOT NULL,
  intended_period_start timestamptz,
  intended_period_end timestamptz,
  paid_at timestamptz,
  created_at timestamptz NOT NULL
);

CREATE TABLE invoice_lines (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  invoice_id uuid NOT NULL REFERENCES invoices (id),
  description text NOT NULL,
  quantity integer NOT NULL,
  discounted_unit_price numeric(20, 2) NOT NULL,
  amount numeric(20, 2) NOT NULL,
  company_refs jsonb,
  service_period_start timestamptz,
  service_period_end timestamptz,
  receipt_attributes jsonb NOT NULL,
  CONSTRAINT invoice_lines_amount_ck CHECK (amount >= 0)
);

CREATE TABLE payment_attempts (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  invoice_id uuid NOT NULL REFERENCES invoices (id),
  provider text NOT NULL DEFAULT 'yookassa',
  provider_payment_id text UNIQUE,
  idempotence_key text NOT NULL UNIQUE,
  request_hash text NOT NULL,
  request_body jsonb NOT NULL,
  amount numeric(20, 2) NOT NULL,
  currency text NOT NULL,
  status text NOT NULL,
  test_mode boolean,
  confirmation_url text,
  created_at timestamptz NOT NULL,
  verified_at timestamptz,
  provider_error text,
  reconcile_attempts integer NOT NULL DEFAULT 0
);

CREATE TABLE billing_webhook_inbox (
  id uuid PRIMARY KEY,
  provider text NOT NULL,
  object_id text NOT NULL,
  event text NOT NULL,
  payload_hash text NOT NULL,
  payload_redacted jsonb NOT NULL,
  received_at timestamptz NOT NULL,
  status text NOT NULL,
  attempts integer NOT NULL DEFAULT 0,
  last_error text,
  tenant_id uuid,
  CONSTRAINT billing_webhook_dedup UNIQUE (provider, object_id, event, payload_hash)
);

CREATE TABLE billing_activations (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  invoice_id uuid NOT NULL UNIQUE REFERENCES invoices (id),
  subscription_id uuid NOT NULL REFERENCES subscriptions (id),
  period_id uuid,
  change_revision integer NOT NULL,
  applied_at timestamptz NOT NULL
);

CREATE TABLE refunds (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  payment_attempt_id uuid NOT NULL REFERENCES payment_attempts (id),
  provider_refund_id text UNIQUE,
  amount numeric(20, 2) NOT NULL,
  status text NOT NULL,
  idempotence_key text NOT NULL UNIQUE,
  reason text NOT NULL,
  created_by uuid,
  verified_at timestamptz,
  created_at timestamptz NOT NULL
);

CREATE TABLE billing_audit (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  actor text NOT NULL,
  action text NOT NULL,
  entity_id uuid,
  evidence_redacted jsonb NOT NULL,
  created_at timestamptz NOT NULL
);

ALTER TABLE billing_periods
  ADD CONSTRAINT billing_periods_no_overlap
  EXCLUDE USING gist (
    subscription_id WITH =,
    tstzrange(start_at, end_at, '[)') WITH &&
  )
  WHERE (status <> 'revoked');

CREATE OR REPLACE FUNCTION forbid_row_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION 'immutable row';
END;
$$;

CREATE TRIGGER tariff_versions_immutable
  BEFORE UPDATE OR DELETE ON tariff_versions
  FOR EACH ROW EXECUTE FUNCTION forbid_row_mutation();

CREATE TRIGGER annual_offer_versions_immutable
  BEFORE UPDATE OR DELETE ON annual_offer_versions
  FOR EACH ROW EXECUTE FUNCTION forbid_row_mutation();

CREATE OR REPLACE FUNCTION forbid_invoice_price_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.list_amount IS DISTINCT FROM OLD.list_amount
     OR NEW.discount_amount IS DISTINCT FROM OLD.discount_amount
     OR NEW.payable_amount IS DISTINCT FROM OLD.payable_amount
     OR NEW.pricing_snapshot IS DISTINCT FROM OLD.pricing_snapshot
     OR NEW.billing_interval IS DISTINCT FROM OLD.billing_interval
     OR NEW.currency IS DISTINCT FROM OLD.currency
     OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
     OR NEW.quote_id IS DISTINCT FROM OLD.quote_id THEN
    RAISE EXCEPTION 'invoice pricing snapshot is immutable';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER invoices_price_immutable
  BEFORE UPDATE ON invoices
  FOR EACH ROW EXECUTE FUNCTION forbid_invoice_price_change();

CREATE OR REPLACE FUNCTION forbid_period_snapshot_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NEW.discount_percent IS DISTINCT FROM OLD.discount_percent
     OR NEW.paid_amount IS DISTINCT FROM OLD.paid_amount
     OR NEW.monthly_base_snapshot IS DISTINCT FROM OLD.monthly_base_snapshot
     OR NEW.interval IS DISTINCT FROM OLD.interval
     OR NEW.start_at IS DISTINCT FROM OLD.start_at
     OR NEW.end_at IS DISTINCT FROM OLD.end_at
     OR NEW.tenant_id IS DISTINCT FROM OLD.tenant_id
     OR NEW.annual_offer_version_id IS DISTINCT FROM OLD.annual_offer_version_id THEN
    RAISE EXCEPTION 'billing period snapshot is immutable';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER billing_periods_snapshot_immutable
  BEFORE UPDATE ON billing_periods
  FOR EACH ROW EXECUTE FUNCTION forbid_period_snapshot_change();

INSERT INTO tariff_versions (
  id, code, version, currency, monthly_first_company_price, monthly_additional_price,
  valid_from, status, tax_config_version, created_at
) VALUES (
  '00000000-0000-4000-8000-000000000001',
  'beta', 1, 'RUB', 2500.00, 1500.00,
  '2026-10-14T00:00:00Z', 'active', NULL, '2026-10-14T00:00:00Z'
);

INSERT INTO annual_offer_versions (
  id, tariff_version_id, discount_percent, status, approved_by, approved_at,
  approval_source, offer_terms_version, valid_from, created_at
) VALUES (
  '00000000-0000-4000-8000-000000000002',
  '00000000-0000-4000-8000-000000000001',
  15.000000, 'approved', 'user', '2026-10-14T00:00:00Z',
  'user', 'beta-2026-10-14', '2026-10-14T00:00:00Z', '2026-10-14T00:00:00Z'
);

CREATE OR REPLACE FUNCTION app_payment_context(p_provider_payment_id text)
RETURNS TABLE(attempt_id uuid, invoice_id uuid, tenant_id uuid, subscription_id uuid)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  SELECT pa.id, pa.invoice_id, pa.tenant_id, i.subscription_id
  FROM payment_attempts AS pa
  JOIN invoices AS i ON i.id = pa.invoice_id
  WHERE pa.provider_payment_id = p_provider_payment_id
$$;

CREATE OR REPLACE FUNCTION app_open_payments()
RETURNS TABLE(attempt_id uuid, provider_payment_id text, tenant_id uuid, idempotence_key text)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  SELECT id, provider_payment_id, tenant_id, idempotence_key
  FROM payment_attempts
  WHERE status IN ('pending', 'unknown', 'waiting_for_capture')
$$;

CREATE OR REPLACE FUNCTION app_pending_outbox()
RETURNS SETOF transactional_email_outbox
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  SELECT * FROM transactional_email_outbox
  WHERE status = 'pending'
  ORDER BY created_at
$$;

CREATE OR REPLACE FUNCTION app_mark_outbox(p_id uuid, p_status text, p_error text)
RETURNS void
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  UPDATE transactional_email_outbox
  SET status = p_status,
      last_error = p_error,
      attempts = attempts + 1,
      sent_at = CASE WHEN p_status = 'sent' THEN now() ELSE sent_at END
  WHERE id = p_id
$$;

CREATE OR REPLACE FUNCTION app_subscriptions_for_reminders()
RETURNS TABLE(
  id uuid,
  tenant_id uuid,
  paid_through timestamptz,
  current_interval text,
  is_renewal_cancelled boolean
)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  SELECT id, tenant_id, paid_through, current_interval, is_renewal_cancelled
  FROM subscriptions
  WHERE paid_through IS NOT NULL
$$;

REVOKE ALL ON FUNCTION app_payment_context(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION app_open_payments() FROM PUBLIC;
REVOKE ALL ON FUNCTION app_pending_outbox() FROM PUBLIC;
REVOKE ALL ON FUNCTION app_mark_outbox(uuid, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION app_subscriptions_for_reminders() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_payment_context(text) TO finpilot_worker;
GRANT EXECUTE ON FUNCTION app_open_payments() TO finpilot_worker;
GRANT EXECUTE ON FUNCTION app_pending_outbox() TO finpilot_worker;
GRANT EXECUTE ON FUNCTION app_mark_outbox(uuid, text, text) TO finpilot_worker;
GRANT EXECUTE ON FUNCTION app_subscriptions_for_reminders() TO finpilot_worker;

ALTER TABLE billing_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_accounts FORCE ROW LEVEL SECURITY;
ALTER TABLE subscriptions ENABLE ROW LEVEL SECURITY;
ALTER TABLE subscriptions FORCE ROW LEVEL SECURITY;
ALTER TABLE billing_periods ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_periods FORCE ROW LEVEL SECURITY;
ALTER TABLE company_entitlements ENABLE ROW LEVEL SECURITY;
ALTER TABLE company_entitlements FORCE ROW LEVEL SECURITY;
ALTER TABLE billing_quotes ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_quotes FORCE ROW LEVEL SECURITY;
ALTER TABLE invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoices FORCE ROW LEVEL SECURITY;
ALTER TABLE invoice_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE invoice_lines FORCE ROW LEVEL SECURITY;
ALTER TABLE payment_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE payment_attempts FORCE ROW LEVEL SECURITY;
ALTER TABLE billing_activations ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_activations FORCE ROW LEVEL SECURITY;
ALTER TABLE refunds ENABLE ROW LEVEL SECURITY;
ALTER TABLE refunds FORCE ROW LEVEL SECURITY;
ALTER TABLE billing_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE billing_audit FORCE ROW LEVEL SECURITY;

CREATE POLICY billing_accounts_tenant ON billing_accounts
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY subscriptions_tenant ON subscriptions
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY billing_periods_tenant ON billing_periods
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY company_entitlements_tenant ON company_entitlements
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY billing_quotes_tenant ON billing_quotes
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY invoices_tenant ON invoices
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY invoice_lines_tenant ON invoice_lines
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY payment_attempts_tenant ON payment_attempts
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY billing_activations_tenant ON billing_activations
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY refunds_tenant ON refunds
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY billing_audit_tenant ON billing_audit
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());

GRANT SELECT ON tariff_versions, annual_offer_versions TO finpilot_app, finpilot_worker;
GRANT USAGE, SELECT ON SEQUENCE invoice_number_seq TO finpilot_app, finpilot_worker;
GRANT SELECT, INSERT, UPDATE ON
  billing_accounts, subscriptions, billing_periods, company_entitlements, billing_quotes,
  invoices, invoice_lines, payment_attempts, billing_activations, refunds, billing_audit
TO finpilot_app, finpilot_worker;
GRANT SELECT, INSERT, UPDATE ON billing_webhook_inbox TO finpilot_app, finpilot_worker;
