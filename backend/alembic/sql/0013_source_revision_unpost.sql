SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE raw_import_rows
  ADD COLUMN IF NOT EXISTS source_revision BIGINT,
  ADD COLUMN IF NOT EXISTS operation TEXT NOT NULL DEFAULT 'upsert';

ALTER TABLE raw_import_rows
  ADD CONSTRAINT raw_import_rows_source_revision_nonneg_chk
  CHECK (source_revision IS NULL OR source_revision >= 0);

ALTER TABLE raw_import_rows
  ADD CONSTRAINT raw_import_rows_operation_chk
  CHECK (operation IN ('upsert', 'unpost'));

ALTER TABLE source_identities
  ADD COLUMN IF NOT EXISTS last_source_revision BIGINT;

ALTER TABLE source_identities
  ADD CONSTRAINT source_identities_last_source_revision_nonneg_chk
  CHECK (last_source_revision IS NULL OR last_source_revision >= 0);

ALTER TABLE raw_import_rows
  DROP CONSTRAINT IF EXISTS raw_import_rows_status_ck;

ALTER TABLE raw_import_rows
  ADD CONSTRAINT raw_import_rows_status_ck CHECK (
    duplicate_status IN (
      'new', 'repeated', 'changed', 'invalid', 'ambiguous', 'linked', 'unpost'
    )
  );
