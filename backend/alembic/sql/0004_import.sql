ALTER TABLE wallets ADD COLUMN code text;
CREATE UNIQUE INDEX uq_wallets_code
  ON wallets (tenant_id, company_id, code)
  WHERE code IS NOT NULL;

ALTER TABLE cash_transactions ADD COLUMN counterparty_inn text;
ALTER TABLE cash_transactions ADD COLUMN counterparty_name text;
CREATE INDEX cash_transactions_match
  ON cash_transactions (tenant_id, company_id, business_date, amount)
  WHERE status = 'posted';

CREATE TABLE source_connections (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  type text NOT NULL,
  name text NOT NULL,
  namespace text NOT NULL,
  authoritative boolean NOT NULL DEFAULT true,
  wallet_id uuid,
  format text NOT NULL,
  encoding text NOT NULL DEFAULT 'utf-8',
  enabled boolean NOT NULL DEFAULT true,
  status text NOT NULL DEFAULT 'active',
  created_at timestamptz NOT NULL,
  CONSTRAINT source_connections_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT source_connections_company_uq UNIQUE (tenant_id, company_id, id),
  CONSTRAINT source_connections_namespace_uq UNIQUE (tenant_id, company_id, namespace),
  CONSTRAINT source_connections_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT source_connections_wallet_fk
    FOREIGN KEY (tenant_id, company_id, wallet_id)
    REFERENCES wallets (tenant_id, company_id, id),
  CONSTRAINT source_connections_type_ck CHECK (type IN ('file', 'clientbank', 'onec')),
  CONSTRAINT source_connections_format_ck CHECK (format IN ('csv', 'xlsx', 'clientbank')),
  CONSTRAINT source_connections_status_ck CHECK (status IN ('active', 'disabled'))
);

CREATE TABLE import_profiles (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  connection_id uuid NOT NULL,
  format text NOT NULL,
  encoding text NOT NULL,
  sheet_name text,
  column_mapping jsonb NOT NULL DEFAULT '{}'::jsonb,
  date_format text NOT NULL DEFAULT 'YYYY-MM-DD',
  decimal_separator text NOT NULL DEFAULT '.',
  sign_policy text NOT NULL DEFAULT 'direction',
  schema_version integer NOT NULL DEFAULT 1,
  CONSTRAINT import_profiles_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT import_profiles_connection_uq UNIQUE (tenant_id, connection_id),
  CONSTRAINT import_profiles_connection_fk
    FOREIGN KEY (tenant_id, connection_id) REFERENCES source_connections (tenant_id, id)
);

CREATE TABLE import_batches (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  connection_id uuid NOT NULL,
  file_hash text NOT NULL,
  file_storage_key text NOT NULL,
  format text NOT NULL,
  status text NOT NULL,
  rows_total integer NOT NULL DEFAULT 0,
  rows_valid integer NOT NULL DEFAULT 0,
  rows_invalid integer NOT NULL DEFAULT 0,
  rows_committed integer NOT NULL DEFAULT 0,
  quality_flags jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at timestamptz NOT NULL,
  completed_at timestamptz,
  CONSTRAINT import_batches_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT import_batches_file_uq UNIQUE (tenant_id, company_id, connection_id, file_hash),
  CONSTRAINT import_batches_connection_fk
    FOREIGN KEY (tenant_id, company_id, connection_id)
    REFERENCES source_connections (tenant_id, company_id, id),
  CONSTRAINT import_batches_status_ck CHECK (
    status IN (
      'received', 'validating', 'preview_ready', 'committing',
      'completed', 'completed_with_errors', 'failed'
    )
  )
);

CREATE TABLE raw_import_rows (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  batch_id uuid NOT NULL,
  row_number integer NOT NULL,
  raw_payload jsonb NOT NULL,
  normalized_payload jsonb,
  validation_errors jsonb NOT NULL DEFAULT '[]'::jsonb,
  duplicate_status text NOT NULL,
  proposed_action text NOT NULL,
  payload_hash text,
  external_id text,
  CONSTRAINT raw_import_rows_batch_uq UNIQUE (batch_id, row_number),
  CONSTRAINT raw_import_rows_batch_fk
    FOREIGN KEY (tenant_id, batch_id) REFERENCES import_batches (tenant_id, id),
  CONSTRAINT raw_import_rows_status_ck CHECK (
    duplicate_status IN ('new', 'repeated', 'changed', 'invalid', 'ambiguous', 'linked')
  ),
  CONSTRAINT raw_import_rows_action_ck CHECK (
    proposed_action IN ('create', 'skip', 'revise', 'link', 'review')
  )
);

CREATE TABLE source_identities (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  connection_id uuid NOT NULL,
  namespace text NOT NULL,
  entity_type text NOT NULL,
  external_id text NOT NULL,
  canonical_entity_id uuid,
  payload_hash text NOT NULL,
  created_at timestamptz NOT NULL,
  CONSTRAINT source_identities_key_uq UNIQUE (tenant_id, company_id, namespace, external_id),
  CONSTRAINT source_identities_connection_fk
    FOREIGN KEY (tenant_id, company_id, connection_id)
    REFERENCES source_connections (tenant_id, company_id, id),
  CONSTRAINT source_identities_tx_fk
    FOREIGN KEY (tenant_id, canonical_entity_id)
    REFERENCES cash_transactions (tenant_id, id)
);

CREATE TABLE classification_rules (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid,
  name text NOT NULL,
  priority integer NOT NULL,
  conditions_json jsonb NOT NULL,
  actions_json jsonb NOT NULL,
  enabled boolean NOT NULL DEFAULT true,
  version integer NOT NULL DEFAULT 1,
  created_at timestamptz NOT NULL,
  CONSTRAINT classification_rules_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id)
);

ALTER TABLE source_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_connections FORCE ROW LEVEL SECURITY;
ALTER TABLE import_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_profiles FORCE ROW LEVEL SECURITY;
ALTER TABLE import_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_batches FORCE ROW LEVEL SECURITY;
ALTER TABLE raw_import_rows ENABLE ROW LEVEL SECURITY;
ALTER TABLE raw_import_rows FORCE ROW LEVEL SECURITY;
ALTER TABLE source_identities ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_identities FORCE ROW LEVEL SECURITY;
ALTER TABLE classification_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE classification_rules FORCE ROW LEVEL SECURITY;

CREATE POLICY source_connections_tenant ON source_connections
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY import_profiles_tenant ON import_profiles
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY import_batches_tenant ON import_batches
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY raw_import_rows_tenant ON raw_import_rows
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY source_identities_tenant ON source_identities
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());
CREATE POLICY classification_rules_tenant ON classification_rules
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());

GRANT SELECT, INSERT, UPDATE ON
  source_connections, import_profiles, import_batches, raw_import_rows,
  source_identities, classification_rules
TO finpilot_app, finpilot_worker;
