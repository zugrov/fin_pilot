ALTER TABLE companies
  ADD CONSTRAINT companies_tenant_id_uq UNIQUE (tenant_id, id);

REVOKE UPDATE ON billing_webhook_inbox FROM finpilot_app;
REVOKE INSERT ON billing_webhook_inbox FROM finpilot_worker;

CREATE TABLE cash_categories (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants (id),
  code text NOT NULL,
  name text NOT NULL,
  parent_id uuid,
  cash_flow_section text NOT NULL,
  direction text NOT NULL,
  exclude_from_operating_metrics boolean NOT NULL DEFAULT false,
  CONSTRAINT cash_categories_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT cash_categories_code_uq UNIQUE (tenant_id, code),
  CONSTRAINT cash_categories_section_ck CHECK (
    cash_flow_section IN ('operating', 'investing', 'financing', 'technical')
  ),
  CONSTRAINT cash_categories_direction_ck CHECK (direction IN ('in', 'out', 'both')),
  CONSTRAINT cash_categories_parent_fk
    FOREIGN KEY (tenant_id, parent_id) REFERENCES cash_categories (tenant_id, id)
);

CREATE TABLE wallets (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants (id),
  company_id uuid NOT NULL,
  name text NOT NULL,
  type text NOT NULL,
  masked_identifier text,
  currency text NOT NULL DEFAULT 'RUB',
  availability_type text NOT NULL,
  available_from timestamptz,
  is_active boolean NOT NULL DEFAULT true,
  minimum_reserve numeric(20, 2) NOT NULL DEFAULT 0,
  created_at timestamptz NOT NULL,
  CONSTRAINT wallets_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT wallets_company_id_uq UNIQUE (tenant_id, company_id, id),
  CONSTRAINT wallets_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT wallets_type_ck CHECK (
    type IN ('bank', 'cash', 'business_owner_card', 'deposit', 'other')
  ),
  CONSTRAINT wallets_currency_ck CHECK (currency = 'RUB'),
  CONSTRAINT wallets_availability_ck CHECK (availability_type IN ('spendable', 'restricted')),
  CONSTRAINT wallets_reserve_ck CHECK (minimum_reserve >= 0)
);

CREATE TABLE wallet_access (
  tenant_id uuid NOT NULL,
  user_id uuid NOT NULL REFERENCES users (id),
  wallet_id uuid NOT NULL,
  can_create boolean NOT NULL DEFAULT false,
  can_read boolean NOT NULL DEFAULT true,
  PRIMARY KEY (user_id, wallet_id),
  CONSTRAINT wallet_access_wallet_fk
    FOREIGN KEY (tenant_id, wallet_id) REFERENCES wallets (tenant_id, id)
);

CREATE TABLE opening_balances (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  wallet_id uuid NOT NULL,
  effective_at timestamptz NOT NULL,
  amount numeric(20, 2) NOT NULL,
  status text NOT NULL,
  created_at timestamptz NOT NULL,
  CONSTRAINT opening_balances_wallet_fk
    FOREIGN KEY (tenant_id, company_id, wallet_id)
    REFERENCES wallets (tenant_id, company_id, id),
  CONSTRAINT opening_balances_status_ck CHECK (status IN ('active', 'replaced'))
);

CREATE UNIQUE INDEX uq_opening_balances_active
  ON opening_balances (wallet_id)
  WHERE status = 'active';

CREATE TABLE transfer_groups (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL REFERENCES tenants (id),
  kind text NOT NULL,
  status text NOT NULL,
  pairing_method text NOT NULL,
  confirmed_by uuid,
  amount numeric(20, 2) NOT NULL,
  currency text NOT NULL,
  created_at timestamptz NOT NULL,
  CONSTRAINT transfer_groups_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT transfer_groups_kind_ck CHECK (kind IN ('internal', 'intercompany')),
  CONSTRAINT transfer_groups_status_ck CHECK (status IN ('linked', 'void')),
  CONSTRAINT transfer_groups_amount_ck CHECK (amount > 0),
  CONSTRAINT transfer_groups_currency_ck CHECK (currency = 'RUB')
);

CREATE TABLE cash_transactions (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  wallet_id uuid NOT NULL,
  business_date date NOT NULL,
  occurred_at timestamptz,
  direction text NOT NULL,
  amount numeric(20, 2) NOT NULL,
  currency text NOT NULL DEFAULT 'RUB',
  category_id uuid,
  description text NOT NULL DEFAULT '',
  document_number text,
  source text NOT NULL,
  status text NOT NULL,
  classification_origin text NOT NULL DEFAULT 'none',
  locked_classification boolean NOT NULL DEFAULT false,
  transfer_group_id uuid,
  created_by uuid NOT NULL,
  version integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CONSTRAINT cash_transactions_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT cash_transactions_wallet_fk
    FOREIGN KEY (tenant_id, company_id, wallet_id)
    REFERENCES wallets (tenant_id, company_id, id),
  CONSTRAINT cash_transactions_category_fk
    FOREIGN KEY (tenant_id, category_id) REFERENCES cash_categories (tenant_id, id),
  CONSTRAINT cash_transactions_transfer_fk
    FOREIGN KEY (tenant_id, transfer_group_id) REFERENCES transfer_groups (tenant_id, id),
  CONSTRAINT cash_transactions_direction_ck CHECK (direction IN ('in', 'out')),
  CONSTRAINT cash_transactions_amount_ck CHECK (amount > 0),
  CONSTRAINT cash_transactions_currency_ck CHECK (currency = 'RUB'),
  CONSTRAINT cash_transactions_source_ck CHECK (source IN ('manual', 'import', 'telegram')),
  CONSTRAINT cash_transactions_status_ck CHECK (status IN ('draft', 'posted', 'void')),
  CONSTRAINT cash_transactions_origin_ck CHECK (
    classification_origin IN ('rule', 'manual', 'none')
  )
);

CREATE INDEX cash_transactions_company_date
  ON cash_transactions (tenant_id, company_id, business_date);
CREATE INDEX cash_transactions_wallet_date
  ON cash_transactions (wallet_id, business_date, status);

CREATE TABLE transaction_revisions (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  transaction_id uuid NOT NULL,
  version integer NOT NULL,
  previous jsonb NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL,
  CONSTRAINT transaction_revisions_tx_fk
    FOREIGN KEY (tenant_id, transaction_id) REFERENCES cash_transactions (tenant_id, id)
);

CREATE FUNCTION guard_posted_cash_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.status = 'posted' AND (
    NEW.amount IS DISTINCT FROM OLD.amount
    OR NEW.direction IS DISTINCT FROM OLD.direction
    OR NEW.business_date IS DISTINCT FROM OLD.business_date
    OR NEW.wallet_id IS DISTINCT FROM OLD.wallet_id
    OR NEW.category_id IS DISTINCT FROM OLD.category_id
    OR NEW.status IS DISTINCT FROM OLD.status
    OR NEW.transfer_group_id IS DISTINCT FROM OLD.transfer_group_id
  ) THEN
    IF current_setting('app.cash_revision', true) IS DISTINCT FROM 'on' THEN
      RAISE EXCEPTION 'posted_requires_revision';
    END IF;
    IF NEW.version <= OLD.version THEN
      RAISE EXCEPTION 'version_not_bumped';
    END IF;
  END IF;
  RETURN NEW;
END $$;

CREATE TRIGGER cash_transactions_posted_guard
  BEFORE UPDATE ON cash_transactions
  FOR EACH ROW EXECUTE FUNCTION guard_posted_cash_change();

CREATE FUNCTION seed_cash_categories(p_tenant uuid) RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO cash_categories (
    id, tenant_id, code, name, cash_flow_section, direction, exclude_from_operating_metrics
  )
  SELECT gen_random_uuid(), p_tenant, v.code, v.name, v.section, v.direction, v.exclude
  FROM (
    VALUES
      ('operating', 'Операционная', 'operating', 'both', false),
      ('investing', 'Инвестиционная', 'investing', 'both', false),
      ('owner_contribution', 'Вклад собственника', 'financing', 'in', false),
      ('loan', 'Займ', 'financing', 'both', false),
      ('technical', 'Техническая', 'technical', 'both', true)
  ) AS v(code, name, section, direction, exclude)
  WHERE NOT EXISTS (
    SELECT 1 FROM cash_categories AS existing
    WHERE existing.tenant_id = p_tenant AND existing.code = v.code
  );
END $$;

SELECT seed_cash_categories(id) FROM tenants;

ALTER TABLE cash_categories ENABLE ROW LEVEL SECURITY;
ALTER TABLE cash_categories FORCE ROW LEVEL SECURITY;
ALTER TABLE wallets ENABLE ROW LEVEL SECURITY;
ALTER TABLE wallets FORCE ROW LEVEL SECURITY;
ALTER TABLE wallet_access ENABLE ROW LEVEL SECURITY;
ALTER TABLE wallet_access FORCE ROW LEVEL SECURITY;
ALTER TABLE opening_balances ENABLE ROW LEVEL SECURITY;
ALTER TABLE opening_balances FORCE ROW LEVEL SECURITY;
ALTER TABLE transfer_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE transfer_groups FORCE ROW LEVEL SECURITY;
ALTER TABLE cash_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE cash_transactions FORCE ROW LEVEL SECURITY;
ALTER TABLE transaction_revisions ENABLE ROW LEVEL SECURITY;
ALTER TABLE transaction_revisions FORCE ROW LEVEL SECURITY;

CREATE POLICY cash_categories_tenant ON cash_categories
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY wallets_tenant ON wallets
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY wallet_access_tenant ON wallet_access
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY opening_balances_tenant ON opening_balances
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY transfer_groups_tenant ON transfer_groups
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY cash_transactions_tenant ON cash_transactions
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY transaction_revisions_tenant ON transaction_revisions
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());

GRANT SELECT, INSERT, UPDATE ON
  cash_categories, wallets, wallet_access, opening_balances, transfer_groups,
  cash_transactions, transaction_revisions
TO finpilot_app, finpilot_worker;

REVOKE ALL ON FUNCTION seed_cash_categories(uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION seed_cash_categories(uuid) TO finpilot_app, finpilot_worker;
