SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM ingestion_deliveries LIMIT 1) THEN
    RAISE EXCEPTION 'downgrade_blocked: есть transport history ingestion_deliveries';
  END IF;
END $$;

ALTER TABLE email_ingestions DROP CONSTRAINT IF EXISTS email_ingestions_delivery_fk;
ALTER TABLE email_ingestions DROP COLUMN IF EXISTS delivery_id;

ALTER TABLE import_batches DROP CONSTRAINT IF EXISTS import_batches_delivery_fk;
ALTER TABLE import_batches DROP COLUMN IF EXISTS delivery_id;

DROP TABLE IF EXISTS ingestion_delivery_parts;
DROP TABLE IF EXISTS ingestion_deliveries;
