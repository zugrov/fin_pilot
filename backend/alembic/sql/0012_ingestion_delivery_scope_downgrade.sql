SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE email_ingestions
  DROP CONSTRAINT IF EXISTS email_ingestions_delivery_scope_fk;

ALTER TABLE email_ingestions
  ADD CONSTRAINT email_ingestions_delivery_fk
  FOREIGN KEY (tenant_id, delivery_id)
  REFERENCES ingestion_deliveries (tenant_id, id);

ALTER TABLE import_batches
  DROP CONSTRAINT IF EXISTS import_batches_delivery_scope_fk;

ALTER TABLE import_batches
  ADD CONSTRAINT import_batches_delivery_fk
  FOREIGN KEY (tenant_id, delivery_id)
  REFERENCES ingestion_deliveries (tenant_id, id);

ALTER TABLE ingestion_delivery_parts
  DROP CONSTRAINT IF EXISTS ingestion_delivery_parts_batch_scope_fk;

ALTER TABLE ingestion_delivery_parts
  ADD CONSTRAINT ingestion_delivery_parts_batch_fk
  FOREIGN KEY (tenant_id, batch_id)
  REFERENCES import_batches (tenant_id, id);

ALTER TABLE ingestion_deliveries
  DROP CONSTRAINT IF EXISTS ingestion_deliveries_connection_id_uq;

ALTER TABLE import_batches
  DROP CONSTRAINT IF EXISTS import_batches_scope_uq;
