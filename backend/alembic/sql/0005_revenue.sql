CREATE TABLE directions (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  code text NOT NULL,
  name text NOT NULL,
  created_at timestamptz NOT NULL,
  CONSTRAINT directions_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT directions_company_id_uq UNIQUE (tenant_id, company_id, id),
  CONSTRAINT directions_code_uq UNIQUE (tenant_id, company_id, code),
  CONSTRAINT directions_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id)
);

CREATE TABLE counterparties (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  inn text,
  name text NOT NULL,
  created_at timestamptz NOT NULL,
  CONSTRAINT counterparties_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT counterparties_company_id_uq UNIQUE (tenant_id, company_id, id),
  CONSTRAINT counterparties_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id)
);

CREATE UNIQUE INDEX uq_counterparties_inn
  ON counterparties (tenant_id, company_id, inn)
  WHERE inn IS NOT NULL;

CREATE TABLE revenue_entries (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  direction_id uuid,
  counterparty_id uuid,
  recognition_date date NOT NULL,
  document_number text,
  external_id text,
  source_connection_id uuid,
  import_batch_id uuid,
  amount_ex_vat numeric(20, 2),
  vat_amount numeric(20, 2),
  amount_inc_vat numeric(20, 2) NOT NULL,
  entry_type text NOT NULL,
  vat_basis text NOT NULL,
  status text NOT NULL,
  source text NOT NULL,
  version integer NOT NULL DEFAULT 1,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CONSTRAINT revenue_entries_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT revenue_entries_company_id_uq UNIQUE (tenant_id, company_id, id),
  CONSTRAINT revenue_entries_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT revenue_entries_direction_fk
    FOREIGN KEY (tenant_id, company_id, direction_id)
    REFERENCES directions (tenant_id, company_id, id),
  CONSTRAINT revenue_entries_counterparty_fk
    FOREIGN KEY (tenant_id, company_id, counterparty_id)
    REFERENCES counterparties (tenant_id, company_id, id),
  CONSTRAINT revenue_entries_connection_fk
    FOREIGN KEY (tenant_id, source_connection_id)
    REFERENCES source_connections (tenant_id, id),
  CONSTRAINT revenue_entries_batch_fk
    FOREIGN KEY (tenant_id, import_batch_id)
    REFERENCES import_batches (tenant_id, id),
  CONSTRAINT revenue_entries_type_ck CHECK (entry_type IN ('sale', 'return')),
  CONSTRAINT revenue_entries_status_ck CHECK (status IN ('posted', 'void')),
  CONSTRAINT revenue_entries_basis_ck CHECK (vat_basis IN ('net', 'unknown')),
  CONSTRAINT revenue_entries_source_ck CHECK (source IN ('manual', 'import')),
  CONSTRAINT revenue_entries_inc_ck CHECK (amount_inc_vat > 0),
  CONSTRAINT revenue_entries_ex_ck CHECK (amount_ex_vat IS NULL OR amount_ex_vat >= 0),
  CONSTRAINT revenue_entries_vat_ck CHECK (vat_amount IS NULL OR vat_amount >= 0),
  CONSTRAINT revenue_entries_net_ck CHECK (
    vat_basis = 'unknown'
    OR (
      amount_ex_vat IS NOT NULL
      AND vat_amount IS NOT NULL
      AND amount_ex_vat + vat_amount = amount_inc_vat
    )
  )
);

CREATE INDEX revenue_entries_period
  ON revenue_entries (tenant_id, company_id, recognition_date)
  WHERE status = 'posted';

CREATE TABLE revenue_cash_matches (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  revenue_entry_id uuid NOT NULL,
  cash_transaction_id uuid NOT NULL,
  amount numeric(20, 2) NOT NULL,
  created_by uuid NOT NULL,
  created_at timestamptz NOT NULL,
  CONSTRAINT revenue_cash_matches_pair_uq
    UNIQUE (tenant_id, revenue_entry_id, cash_transaction_id),
  CONSTRAINT revenue_cash_matches_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT revenue_cash_matches_revenue_fk
    FOREIGN KEY (tenant_id, revenue_entry_id) REFERENCES revenue_entries (tenant_id, id),
  CONSTRAINT revenue_cash_matches_cash_fk
    FOREIGN KEY (tenant_id, cash_transaction_id)
    REFERENCES cash_transactions (tenant_id, id),
  CONSTRAINT revenue_cash_matches_amount_ck CHECK (amount > 0)
);

ALTER TABLE source_connections ADD COLUMN dataset text NOT NULL DEFAULT 'cash';
ALTER TABLE source_connections ADD COLUMN coverage_through date;
ALTER TABLE source_connections ADD COLUMN vat_basis text NOT NULL DEFAULT 'net';
ALTER TABLE source_connections ADD CONSTRAINT source_connections_dataset_ck
  CHECK (dataset IN ('cash', 'revenue'));
ALTER TABLE source_connections ADD CONSTRAINT source_connections_vat_ck
  CHECK (vat_basis IN ('net', 'unknown'));
ALTER TABLE source_connections ADD CONSTRAINT source_connections_revenue_format_ck
  CHECK (dataset = 'cash' OR (type = 'file' AND format = 'csv'));

ALTER TABLE source_identities ADD COLUMN revenue_entry_id uuid;
ALTER TABLE source_identities ADD CONSTRAINT source_identities_revenue_fk
  FOREIGN KEY (tenant_id, revenue_entry_id) REFERENCES revenue_entries (tenant_id, id);
ALTER TABLE source_identities ADD CONSTRAINT source_identities_target_ck CHECK (
  (
    entity_type = 'cash_transaction'
    AND canonical_entity_id IS NOT NULL
    AND revenue_entry_id IS NULL
  )
  OR (
    entity_type = 'revenue_entry'
    AND revenue_entry_id IS NOT NULL
    AND canonical_entity_id IS NULL
  )
);

ALTER TABLE directions ENABLE ROW LEVEL SECURITY;
ALTER TABLE directions FORCE ROW LEVEL SECURITY;
ALTER TABLE counterparties ENABLE ROW LEVEL SECURITY;
ALTER TABLE counterparties FORCE ROW LEVEL SECURITY;
ALTER TABLE revenue_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE revenue_entries FORCE ROW LEVEL SECURITY;
ALTER TABLE revenue_cash_matches ENABLE ROW LEVEL SECURITY;
ALTER TABLE revenue_cash_matches FORCE ROW LEVEL SECURITY;

CREATE POLICY directions_tenant ON directions
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY counterparties_tenant ON counterparties
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY revenue_entries_tenant ON revenue_entries
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY revenue_cash_matches_tenant ON revenue_cash_matches
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());

GRANT SELECT, INSERT, UPDATE ON
  directions, counterparties, revenue_entries, revenue_cash_matches
TO finpilot_app, finpilot_worker;
