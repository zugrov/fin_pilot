DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'finpilot_app') THEN
    CREATE ROLE finpilot_app NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'finpilot_worker') THEN
    CREATE ROLE finpilot_worker NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB;
  END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO finpilot_app, finpilot_worker;

CREATE OR REPLACE FUNCTION app_tenant() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid
$$;

CREATE OR REPLACE FUNCTION app_user() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT NULLIF(current_setting('app.user_id', true), '')::uuid
$$;

GRANT EXECUTE ON FUNCTION app_tenant() TO finpilot_app, finpilot_worker;
GRANT EXECUTE ON FUNCTION app_user() TO finpilot_app, finpilot_worker;

CREATE TABLE users (
  id uuid PRIMARY KEY,
  email text NOT NULL,
  normalized_email text NOT NULL UNIQUE,
  name text NOT NULL,
  password_hash text NOT NULL,
  email_verified_at timestamptz,
  status text NOT NULL DEFAULT 'active',
  password_changed_at timestamptz,
  created_at timestamptz NOT NULL,
  CONSTRAINT users_status_ck CHECK (status IN ('active', 'blocked'))
);

CREATE TABLE sessions (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users (id),
  token_hash text NOT NULL UNIQUE,
  csrf_secret text NOT NULL,
  created_at timestamptz NOT NULL,
  last_seen_at timestamptz NOT NULL,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  user_agent text
);

CREATE TABLE verification_tokens (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users (id),
  token_hash text NOT NULL UNIQUE,
  purpose text NOT NULL,
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  new_email text,
  created_at timestamptz NOT NULL
);

CREATE TABLE transactional_email_outbox (
  id uuid PRIMARY KEY,
  category text NOT NULL,
  type text NOT NULL,
  to_email text NOT NULL,
  template_key text NOT NULL,
  payload_redacted jsonb NOT NULL,
  idempotency_key text NOT NULL UNIQUE,
  status text NOT NULL DEFAULT 'pending',
  attempts integer NOT NULL DEFAULT 0,
  next_attempt_at timestamptz,
  last_error text,
  created_at timestamptz NOT NULL,
  sent_at timestamptz,
  tenant_id uuid,
  user_id uuid,
  company_id uuid
);

CREATE TABLE audit_log (
  id uuid PRIMARY KEY,
  tenant_id uuid,
  user_id uuid,
  action text NOT NULL,
  entity_type text NOT NULL,
  entity_id uuid,
  before_redacted jsonb,
  after_redacted jsonb,
  request_id text,
  created_at timestamptz NOT NULL
);

CREATE TABLE tenants (
  id uuid PRIMARY KEY,
  name text NOT NULL,
  default_timezone text NOT NULL DEFAULT 'Europe/Moscow',
  is_live boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL
);

CREATE TABLE memberships (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants (id),
  user_id uuid NOT NULL REFERENCES users (id),
  role text NOT NULL,
  status text NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL,
  CONSTRAINT memberships_role_ck CHECK (
    role IN (
      'owner', 'finance_manager', 'accountant', 'viewer', 'operator', 'billing_manager'
    )
  ),
  CONSTRAINT memberships_tenant_user_uq UNIQUE (tenant_id, user_id)
);

CREATE TABLE companies (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants (id),
  name text NOT NULL,
  legal_name text,
  inn text,
  kind text NOT NULL DEFAULT 'company',
  currency text NOT NULL DEFAULT 'RUB',
  timezone text NOT NULL DEFAULT 'Europe/Moscow',
  status text NOT NULL DEFAULT 'draft',
  min_cash_reserve numeric(20, 2),
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CONSTRAINT companies_kind_ck CHECK (kind IN ('company', 'ip')),
  CONSTRAINT companies_status_ck CHECK (status IN ('draft', 'active', 'archived'))
);

CREATE UNIQUE INDEX uq_companies_active_inn ON companies (tenant_id, inn)
  WHERE inn IS NOT NULL AND status <> 'archived';

CREATE INDEX ix_companies_tenant ON companies (tenant_id);

CREATE TABLE company_access (
  tenant_id uuid NOT NULL REFERENCES tenants (id),
  user_id uuid NOT NULL REFERENCES users (id),
  company_id uuid NOT NULL REFERENCES companies (id),
  role_override text,
  PRIMARY KEY (tenant_id, user_id, company_id)
);

CREATE TABLE invitations (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants (id),
  email text NOT NULL,
  normalized_email text NOT NULL,
  role text NOT NULL,
  token_hash text NOT NULL UNIQUE,
  expires_at timestamptz NOT NULL,
  used_at timestamptz,
  invited_by uuid NOT NULL REFERENCES users (id),
  status text NOT NULL DEFAULT 'pending',
  created_at timestamptz NOT NULL
);

CREATE TABLE idempotency_records (
  id uuid PRIMARY KEY,
  tenant_id uuid,
  user_id uuid NOT NULL REFERENCES users (id),
  scope text NOT NULL,
  idempotency_key text NOT NULL,
  request_hash text NOT NULL,
  status_code integer NOT NULL,
  response_body jsonb NOT NULL,
  payment_attempt_id uuid,
  created_at timestamptz NOT NULL,
  CONSTRAINT idempotency_user_scope_key_uq UNIQUE (user_id, scope, idempotency_key)
);

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
CREATE POLICY tenants_all ON tenants
  FOR ALL
  USING (
    id = app_tenant()
    OR EXISTS (
      SELECT 1 FROM memberships AS member
      WHERE member.tenant_id = tenants.id AND member.user_id = app_user()
    )
  )
  WITH CHECK (id = app_tenant());

ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY memberships_all ON memberships
  FOR ALL
  USING (tenant_id = app_tenant())
  WITH CHECK (tenant_id = app_tenant());
CREATE POLICY memberships_own_select ON memberships
  FOR SELECT
  USING (user_id = app_user());

ALTER TABLE companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE companies FORCE ROW LEVEL SECURITY;
CREATE POLICY companies_tenant ON companies
  FOR ALL
  USING (tenant_id = app_tenant())
  WITH CHECK (tenant_id = app_tenant());

ALTER TABLE company_access ENABLE ROW LEVEL SECURITY;
ALTER TABLE company_access FORCE ROW LEVEL SECURITY;
CREATE POLICY company_access_tenant ON company_access
  FOR ALL
  USING (tenant_id = app_tenant())
  WITH CHECK (tenant_id = app_tenant());

ALTER TABLE invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE invitations FORCE ROW LEVEL SECURITY;
CREATE POLICY invitations_tenant ON invitations
  FOR ALL
  USING (tenant_id = app_tenant())
  WITH CHECK (tenant_id = app_tenant());

ALTER TABLE transactional_email_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE transactional_email_outbox FORCE ROW LEVEL SECURITY;
CREATE POLICY outbox_insert ON transactional_email_outbox
  FOR INSERT
  WITH CHECK (tenant_id IS NULL OR tenant_id = app_tenant());
CREATE POLICY outbox_select ON transactional_email_outbox
  FOR SELECT
  USING (
    (tenant_id IS NOT NULL AND tenant_id = app_tenant())
    OR (user_id IS NOT NULL AND user_id = app_user())
  );

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;
CREATE POLICY audit_insert ON audit_log
  FOR INSERT
  WITH CHECK (tenant_id IS NULL OR tenant_id = app_tenant());
CREATE POLICY audit_select ON audit_log
  FOR SELECT
  USING (
    (tenant_id IS NOT NULL AND tenant_id = app_tenant())
    OR (user_id IS NOT NULL AND user_id = app_user())
  );

ALTER TABLE idempotency_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE idempotency_records FORCE ROW LEVEL SECURITY;
CREATE POLICY idempotency_all ON idempotency_records
  FOR ALL
  USING (user_id = app_user() OR tenant_id = app_tenant())
  WITH CHECK (user_id = app_user());

CREATE OR REPLACE FUNCTION app_invitation_context(p_token_hash text)
RETURNS TABLE(id uuid, tenant_id uuid)
LANGUAGE sql SECURITY DEFINER SET search_path = public AS $$
  SELECT id, tenant_id FROM invitations WHERE token_hash = p_token_hash
$$;

REVOKE ALL ON FUNCTION app_invitation_context(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_invitation_context(text) TO finpilot_app, finpilot_worker;

GRANT SELECT, INSERT, UPDATE ON
  users, sessions, verification_tokens, transactional_email_outbox, audit_log,
  tenants, memberships, companies, company_access, invitations, idempotency_records
TO finpilot_app, finpilot_worker;
