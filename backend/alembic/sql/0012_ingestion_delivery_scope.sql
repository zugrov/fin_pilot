SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $$
DECLARE
  bad_parts bigint;
  bad_batches bigint;
  bad_email bigint;
BEGIN
  SELECT count(*) INTO bad_parts
  FROM ingestion_delivery_parts p
  JOIN import_batches b
    ON b.tenant_id = p.tenant_id AND b.id = p.batch_id
  WHERE p.batch_id IS NOT NULL
    AND (
      p.company_id IS DISTINCT FROM b.company_id
      OR p.connection_id IS DISTINCT FROM b.connection_id
    );

  SELECT count(*) INTO bad_batches
  FROM import_batches b
  JOIN ingestion_deliveries d
    ON d.tenant_id = b.tenant_id AND d.id = b.delivery_id
  WHERE b.delivery_id IS NOT NULL
    AND (
      b.company_id IS DISTINCT FROM d.company_id
      OR b.connection_id IS DISTINCT FROM d.connection_id
    );

  SELECT count(*) INTO bad_email
  FROM email_ingestions e
  JOIN ingestion_deliveries d
    ON d.tenant_id = e.tenant_id AND d.id = e.delivery_id
  WHERE e.delivery_id IS NOT NULL
    AND e.connection_id IS DISTINCT FROM d.connection_id;

  IF bad_parts > 0 THEN
    RAISE EXCEPTION
      'upgrade_blocked: ingestion_delivery_parts.batch_id scope mismatch (% rows)',
      bad_parts;
  END IF;

  IF bad_batches > 0 THEN
    RAISE EXCEPTION
      'upgrade_blocked: import_batches.delivery_id scope mismatch (% rows)',
      bad_batches;
  END IF;

  IF bad_email > 0 THEN
    RAISE EXCEPTION
      'upgrade_blocked: email_ingestions.delivery_id connection mismatch (% rows)',
      bad_email;
  END IF;
END $$;

ALTER TABLE import_batches
  ADD CONSTRAINT import_batches_scope_uq
  UNIQUE (tenant_id, company_id, connection_id, id);

ALTER TABLE ingestion_deliveries
  ADD CONSTRAINT ingestion_deliveries_connection_id_uq
  UNIQUE (tenant_id, connection_id, id);

ALTER TABLE ingestion_delivery_parts
  DROP CONSTRAINT ingestion_delivery_parts_batch_fk;

ALTER TABLE ingestion_delivery_parts
  ADD CONSTRAINT ingestion_delivery_parts_batch_scope_fk
  FOREIGN KEY (tenant_id, company_id, connection_id, batch_id)
  REFERENCES import_batches (tenant_id, company_id, connection_id, id);

ALTER TABLE import_batches
  DROP CONSTRAINT import_batches_delivery_fk;

ALTER TABLE import_batches
  ADD CONSTRAINT import_batches_delivery_scope_fk
  FOREIGN KEY (tenant_id, company_id, connection_id, delivery_id)
  REFERENCES ingestion_deliveries (tenant_id, company_id, connection_id, id);

ALTER TABLE email_ingestions
  DROP CONSTRAINT email_ingestions_delivery_fk;

ALTER TABLE email_ingestions
  ADD CONSTRAINT email_ingestions_delivery_scope_fk
  FOREIGN KEY (tenant_id, connection_id, delivery_id)
  REFERENCES ingestion_deliveries (tenant_id, connection_id, id);
