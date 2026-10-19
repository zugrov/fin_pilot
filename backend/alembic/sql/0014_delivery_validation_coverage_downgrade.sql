DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM dataset_coverage LIMIT 1) THEN
    RAISE EXCEPTION 'downgrade_blocked: есть dataset_coverage';
  END IF;
  IF EXISTS (
    SELECT 1 FROM ingestion_deliveries
    WHERE validation_status <> 'not_checked'
       OR control_totals_claim IS NOT NULL
       OR envelope_schema_version IS NOT NULL
    LIMIT 1
  ) THEN
    RAISE EXCEPTION 'downgrade_blocked: есть delivery validation metadata';
  END IF;
END $$;

DROP TABLE IF EXISTS dataset_coverage;

ALTER TABLE ingestion_deliveries
  DROP CONSTRAINT IF EXISTS ingestion_deliveries_validation_status_ck,
  DROP CONSTRAINT IF EXISTS ingestion_deliveries_ingest_mode_ck;

ALTER TABLE ingestion_deliveries
  DROP COLUMN IF EXISTS validation_block_reasons,
  DROP COLUMN IF EXISTS validation_status,
  DROP COLUMN IF EXISTS control_totals_calculated,
  DROP COLUMN IF EXISTS envelope_metadata,
  DROP COLUMN IF EXISTS completeness_claim,
  DROP COLUMN IF EXISTS control_totals_claim,
  DROP COLUMN IF EXISTS period_timezone,
  DROP COLUMN IF EXISTS period_to,
  DROP COLUMN IF EXISTS period_from,
  DROP COLUMN IF EXISTS ingest_mode,
  DROP COLUMN IF EXISTS envelope_schema_version;
