CREATE TABLE import_source_fingerprints (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  import_batch_id uuid,
  profile_code text NOT NULL,
  content_sha256 char(64) NOT NULL,
  byte_size bigint NOT NULL DEFAULT 0,
  parser_version text,
  period_from date,
  period_to date,
  registered_at timestamptz NOT NULL,
  CONSTRAINT import_source_fingerprints_tenant_uq UNIQUE (tenant_id, id),
  CONSTRAINT import_source_fingerprints_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT import_source_fingerprints_batch_fk
    FOREIGN KEY (tenant_id, import_batch_id) REFERENCES import_batches (tenant_id, id),
  CONSTRAINT import_source_fingerprints_content_uq
    UNIQUE (tenant_id, company_id, profile_code, content_sha256)
);

CREATE INDEX import_source_fingerprints_batch_idx
  ON import_source_fingerprints (tenant_id, import_batch_id)
  WHERE import_batch_id IS NOT NULL;

CREATE TABLE import_row_lineage (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  raw_import_row_id uuid NOT NULL,
  source_identity_id uuid,
  entity_kind text NOT NULL,
  entity_id uuid NOT NULL,
  line_index integer NOT NULL,
  payload_hash char(64) NOT NULL,
  linked_at timestamptz NOT NULL,
  CONSTRAINT import_row_lineage_tenant_uq UNIQUE (tenant_id, id),
  CONSTRAINT import_row_lineage_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT import_row_lineage_row_fk
    FOREIGN KEY (raw_import_row_id) REFERENCES raw_import_rows (id),
  CONSTRAINT import_row_lineage_identity_fk
    FOREIGN KEY (source_identity_id) REFERENCES source_identities (id),
  CONSTRAINT import_row_lineage_entity_kind_ck CHECK (
    entity_kind IN ('cash_transaction', 'revenue_entry', 'planned_event', 'budget_line')
  )
);

CREATE INDEX import_row_lineage_entity_idx
  ON import_row_lineage (tenant_id, company_id, entity_kind, entity_id);

CREATE INDEX import_row_lineage_row_idx
  ON import_row_lineage (tenant_id, raw_import_row_id);

CREATE TABLE reconciliation_run (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  run_kind text NOT NULL,
  period_year integer NOT NULL,
  period_month integer NOT NULL,
  input_fingerprints jsonb NOT NULL DEFAULT '[]'::jsonb,
  input_hashes jsonb NOT NULL DEFAULT '{}'::jsonb,
  metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
  group_refs jsonb NOT NULL DEFAULT '[]'::jsonb,
  engine_version text NOT NULL,
  created_by_user_id uuid NOT NULL,
  created_at timestamptz NOT NULL,
  supersedes_run_id uuid,
  CONSTRAINT reconciliation_run_tenant_uq UNIQUE (tenant_id, id),
  CONSTRAINT reconciliation_run_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT reconciliation_run_user_fk
    FOREIGN KEY (created_by_user_id) REFERENCES users (id),
  CONSTRAINT reconciliation_run_supersedes_fk
    FOREIGN KEY (tenant_id, supersedes_run_id) REFERENCES reconciliation_run (tenant_id, id),
  CONSTRAINT reconciliation_run_kind_ck CHECK (run_kind IN ('bank_card_51')),
  CONSTRAINT reconciliation_run_period_month_ck CHECK (period_month BETWEEN 1 AND 12)
);

CREATE INDEX reconciliation_run_period_idx
  ON reconciliation_run (tenant_id, company_id, period_year, period_month, created_at DESC);

ALTER TABLE import_source_fingerprints ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_source_fingerprints FORCE ROW LEVEL SECURITY;
ALTER TABLE import_row_lineage ENABLE ROW LEVEL SECURITY;
ALTER TABLE import_row_lineage FORCE ROW LEVEL SECURITY;
ALTER TABLE reconciliation_run ENABLE ROW LEVEL SECURITY;
ALTER TABLE reconciliation_run FORCE ROW LEVEL SECURITY;

CREATE POLICY import_source_fingerprints_tenant ON import_source_fingerprints
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());

CREATE POLICY import_row_lineage_tenant ON import_row_lineage
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());

CREATE POLICY reconciliation_run_tenant ON reconciliation_run
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());

GRANT SELECT, INSERT, UPDATE ON import_source_fingerprints TO finpilot_app, finpilot_worker;
GRANT SELECT, INSERT ON import_row_lineage TO finpilot_app, finpilot_worker;
GRANT SELECT, INSERT ON reconciliation_run TO finpilot_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON reconciliation_run TO finpilot_worker;

REVOKE UPDATE, DELETE ON reconciliation_run FROM finpilot_app;

CREATE OR REPLACE FUNCTION reconciliation_run_write_guard()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
  IF TG_OP = 'DELETE'
    AND current_setting('app.reconciliation_run_retention', true) = '1' THEN
    RETURN OLD;
  END IF;
  RAISE EXCEPTION 'reconciliation_run is append-only';
END;
$$;

CREATE TRIGGER reconciliation_run_immutable_trg
  BEFORE UPDATE OR DELETE ON reconciliation_run
  FOR EACH ROW
  EXECUTE FUNCTION reconciliation_run_write_guard();

CREATE OR REPLACE FUNCTION app_expire_reconciliation_runs(
  p_before timestamptz,
  p_limit integer DEFAULT 500
)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
  v_row reconciliation_run%ROWTYPE;
  v_count integer := 0;
BEGIN
  PERFORM set_config('app.reconciliation_run_retention', '1', true);
  FOR v_row IN
    SELECT *
    FROM reconciliation_run
    WHERE created_at < p_before
    ORDER BY created_at
    LIMIT p_limit
  LOOP
    DELETE FROM reconciliation_run
    WHERE tenant_id = v_row.tenant_id AND id = v_row.id;
    v_count := v_count + 1;
  END LOOP;
  PERFORM set_config('app.reconciliation_run_retention', '', true);
  RETURN v_count;
END;
$$;

ALTER FUNCTION app_expire_reconciliation_runs(timestamptz, integer) OWNER TO finpilot_worker;
REVOKE ALL ON FUNCTION app_expire_reconciliation_runs(timestamptz, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_expire_reconciliation_runs(timestamptz, integer)
  TO finpilot_worker;

CREATE POLICY reconciliation_run_worker_select ON reconciliation_run
  AS PERMISSIVE
  FOR SELECT
  TO finpilot_worker
  USING (
    tenant_id = app_tenant()
    OR current_setting('app.reconciliation_run_retention', true) = '1'
  );

CREATE POLICY reconciliation_run_retention ON reconciliation_run
  AS PERMISSIVE
  FOR DELETE
  TO finpilot_worker
  USING (
    tenant_id = app_tenant()
    OR current_setting('app.reconciliation_run_retention', true) = '1'
  );

ALTER TABLE reconciliation_run ENABLE ROW LEVEL SECURITY;
