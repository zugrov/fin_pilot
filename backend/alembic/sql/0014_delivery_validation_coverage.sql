ALTER TABLE ingestion_deliveries
  ADD COLUMN envelope_schema_version VARCHAR(16),
  ADD COLUMN ingest_mode VARCHAR(16),
  ADD COLUMN period_from DATE,
  ADD COLUMN period_to DATE,
  ADD COLUMN period_timezone VARCHAR(64),
  ADD COLUMN control_totals_claim JSONB,
  ADD COLUMN completeness_claim JSONB,
  ADD COLUMN envelope_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  ADD COLUMN control_totals_calculated JSONB,
  ADD COLUMN validation_status VARCHAR(32) NOT NULL DEFAULT 'not_checked',
  ADD COLUMN validation_block_reasons JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE ingestion_deliveries
  ADD CONSTRAINT ingestion_deliveries_ingest_mode_ck
    CHECK (ingest_mode IS NULL OR ingest_mode IN ('delta', 'snapshot')),
  ADD CONSTRAINT ingestion_deliveries_validation_status_ck
    CHECK (
      validation_status IN (
        'not_checked', 'matched', 'mismatch', 'not_verifiable'
      )
    );

CREATE TABLE dataset_coverage (
  id UUID PRIMARY KEY,
  tenant_id UUID NOT NULL,
  company_id UUID NOT NULL,
  connection_id UUID NOT NULL,
  dataset VARCHAR(32) NOT NULL,
  period_start DATE NOT NULL,
  period_end DATE NOT NULL,
  period_timezone VARCHAR(64) NOT NULL,
  version INTEGER NOT NULL DEFAULT 1,
  supersedes_id UUID,
  state VARCHAR(16) NOT NULL,
  claim JSONB NOT NULL DEFAULT '{}'::jsonb,
  evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
  delivery_id UUID,
  reconciled_by UUID,
  reconciled_at TIMESTAMPTZ,
  reconciliation_basis TEXT,
  created_at TIMESTAMPTZ NOT NULL,
  updated_at TIMESTAMPTZ NOT NULL,
  CONSTRAINT dataset_coverage_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT dataset_coverage_state_ck
    CHECK (state IN ('unknown', 'claimed', 'reconciled', 'superseded')),
  CONSTRAINT dataset_coverage_company_fk
    FOREIGN KEY (tenant_id, company_id)
    REFERENCES companies (tenant_id, id),
  CONSTRAINT dataset_coverage_connection_fk
    FOREIGN KEY (tenant_id, company_id, connection_id)
    REFERENCES source_connections (tenant_id, company_id, id),
  CONSTRAINT dataset_coverage_delivery_fk
    FOREIGN KEY (tenant_id, delivery_id)
    REFERENCES ingestion_deliveries (tenant_id, id),
  CONSTRAINT dataset_coverage_supersedes_fk
    FOREIGN KEY (tenant_id, supersedes_id)
    REFERENCES dataset_coverage (tenant_id, id)
);

CREATE INDEX dataset_coverage_scope_idx
  ON dataset_coverage (tenant_id, company_id, connection_id, dataset, period_start, period_end);

CREATE INDEX dataset_coverage_delivery_idx
  ON dataset_coverage (tenant_id, delivery_id)
  WHERE delivery_id IS NOT NULL;

ALTER TABLE dataset_coverage ENABLE ROW LEVEL SECURITY;
ALTER TABLE dataset_coverage FORCE ROW LEVEL SECURITY;

CREATE POLICY dataset_coverage_tenant ON dataset_coverage
  USING (tenant_id = current_setting('app.tenant_id', true)::uuid);

GRANT SELECT, INSERT, UPDATE ON dataset_coverage TO finpilot_app, finpilot_worker;
