CREATE TABLE ingestion_deliveries (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  company_id uuid NOT NULL,
  connection_id uuid NOT NULL,
  channel text NOT NULL,
  delivery_key text NOT NULL,
  request_fingerprint text NOT NULL,
  transport_status text NOT NULL,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CONSTRAINT ingestion_deliveries_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT ingestion_deliveries_company_uq UNIQUE (tenant_id, company_id, id),
  CONSTRAINT ingestion_deliveries_connection_fk
    FOREIGN KEY (tenant_id, company_id, connection_id)
    REFERENCES source_connections (tenant_id, company_id, id),
  CONSTRAINT ingestion_deliveries_channel_ck
    CHECK (channel IN ('ui', 'email', 'api')),
  CONSTRAINT ingestion_deliveries_transport_ck
    CHECK (
      transport_status IN (
        'partially_received',
        'transport_complete',
        'duplicate_transport',
        'transport_rejected'
      )
    ),
  CONSTRAINT ingestion_deliveries_key_uq
    UNIQUE (tenant_id, company_id, connection_id, delivery_key),
  CONSTRAINT ingestion_deliveries_scope_uq
    UNIQUE (tenant_id, company_id, connection_id, id)
);

CREATE TABLE ingestion_delivery_parts (
  id uuid PRIMARY KEY,
  tenant_id uuid NOT NULL,
  delivery_id uuid NOT NULL,
  company_id uuid NOT NULL,
  connection_id uuid NOT NULL,
  part_index integer NOT NULL,
  content_hash text NOT NULL,
  batch_id uuid,
  part_status text NOT NULL,
  error_code text,
  created_at timestamptz NOT NULL,
  updated_at timestamptz NOT NULL,
  CONSTRAINT ingestion_delivery_parts_tenant_id_uq UNIQUE (tenant_id, id),
  CONSTRAINT ingestion_delivery_parts_delivery_fk
    FOREIGN KEY (tenant_id, delivery_id)
    REFERENCES ingestion_deliveries (tenant_id, id),
  CONSTRAINT ingestion_delivery_parts_batch_fk
    FOREIGN KEY (tenant_id, batch_id)
    REFERENCES import_batches (tenant_id, id),
  CONSTRAINT ingestion_delivery_parts_delivery_scope_fk
    FOREIGN KEY (tenant_id, company_id, connection_id, delivery_id)
    REFERENCES ingestion_deliveries (tenant_id, company_id, connection_id, id),
  CONSTRAINT ingestion_delivery_parts_part_index_uq
    UNIQUE (tenant_id, delivery_id, part_index),
  CONSTRAINT ingestion_delivery_parts_status_ck
    CHECK (part_status IN ('pending', 'preview', 'failed', 'ignored', 'skipped'))
);

ALTER TABLE import_batches
  ADD COLUMN delivery_id uuid;

ALTER TABLE import_batches
  ADD CONSTRAINT import_batches_delivery_fk
    FOREIGN KEY (tenant_id, delivery_id)
    REFERENCES ingestion_deliveries (tenant_id, id);

ALTER TABLE email_ingestions
  ADD COLUMN delivery_id uuid;

ALTER TABLE email_ingestions
  ADD CONSTRAINT email_ingestions_delivery_fk
    FOREIGN KEY (tenant_id, delivery_id)
    REFERENCES ingestion_deliveries (tenant_id, id);

ALTER TABLE ingestion_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingestion_deliveries FORCE ROW LEVEL SECURITY;
CREATE POLICY ingestion_deliveries_tenant ON ingestion_deliveries
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());

ALTER TABLE ingestion_delivery_parts ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingestion_delivery_parts FORCE ROW LEVEL SECURITY;
CREATE POLICY ingestion_delivery_parts_tenant ON ingestion_delivery_parts
  FOR ALL USING (tenant_id = app_tenant()) WITH CHECK (tenant_id = app_tenant());

GRANT SELECT, INSERT, UPDATE ON ingestion_deliveries TO finpilot_app, finpilot_worker;
GRANT SELECT, INSERT, UPDATE ON ingestion_delivery_parts TO finpilot_app, finpilot_worker;
