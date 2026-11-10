CREATE TABLE source_correction_finding (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  kind text NOT NULL,
  severity text NOT NULL DEFAULT 'warning',
  fingerprint_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  lineage_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
  import_batch_id uuid,
  period_from date,
  period_to date,
  details jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL,
  CONSTRAINT source_correction_finding_tenant_uq UNIQUE (tenant_id, id),
  CONSTRAINT source_correction_finding_company_fk
    FOREIGN KEY (tenant_id, company_id) REFERENCES companies (tenant_id, id),
  CONSTRAINT source_correction_finding_batch_fk
    FOREIGN KEY (tenant_id, import_batch_id) REFERENCES import_batches (tenant_id, id),
  CONSTRAINT source_correction_finding_kind_ck CHECK (
    kind IN ('duplicate_suspect', 'period_overlap', 'internal_transfer')
  ),
  CONSTRAINT source_correction_finding_severity_ck CHECK (
    severity IN ('info', 'warning')
  )
);

CREATE INDEX source_correction_finding_company_idx
  ON source_correction_finding (tenant_id, company_id, kind, created_at DESC);

CREATE INDEX source_correction_finding_batch_idx
  ON source_correction_finding (tenant_id, import_batch_id)
  WHERE import_batch_id IS NOT NULL;

ALTER TABLE source_correction_finding ENABLE ROW LEVEL SECURITY;
ALTER TABLE source_correction_finding FORCE ROW LEVEL SECURITY;

CREATE POLICY source_correction_finding_tenant ON source_correction_finding
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());

GRANT SELECT, INSERT ON source_correction_finding TO finpilot_app, finpilot_worker;
