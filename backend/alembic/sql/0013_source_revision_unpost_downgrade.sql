SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM source_identities
    WHERE last_source_revision IS NOT NULL
    LIMIT 1
  ) THEN
    RAISE EXCEPTION 'downgrade_blocked: есть revision watermark в source_identities';
  END IF;
  IF EXISTS (
    SELECT 1 FROM raw_import_rows
    WHERE operation <> 'upsert'
    LIMIT 1
  ) THEN
    RAISE EXCEPTION 'downgrade_blocked: есть non-legacy operation в raw_import_rows';
  END IF;
  IF EXISTS (
    SELECT 1 FROM raw_import_rows
    WHERE duplicate_status = 'unpost'
    LIMIT 1
  ) THEN
    RAISE EXCEPTION 'downgrade_blocked: есть unpost rows в raw_import_rows';
  END IF;
END $$;

ALTER TABLE source_identities
  DROP CONSTRAINT IF EXISTS source_identities_last_source_revision_nonneg_chk;

ALTER TABLE source_identities
  DROP COLUMN IF EXISTS last_source_revision;

ALTER TABLE raw_import_rows
  DROP CONSTRAINT IF EXISTS raw_import_rows_operation_chk;

ALTER TABLE raw_import_rows
  DROP CONSTRAINT IF EXISTS raw_import_rows_source_revision_nonneg_chk;

ALTER TABLE raw_import_rows
  DROP COLUMN IF EXISTS operation;

ALTER TABLE raw_import_rows
  DROP COLUMN IF EXISTS source_revision;

ALTER TABLE raw_import_rows
  DROP CONSTRAINT IF EXISTS raw_import_rows_status_ck;

ALTER TABLE raw_import_rows
  ADD CONSTRAINT raw_import_rows_status_ck CHECK (
    duplicate_status IN ('new', 'repeated', 'changed', 'invalid', 'ambiguous', 'linked')
  );
