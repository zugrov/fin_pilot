DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM reconciliation_run LIMIT 1) THEN
    RAISE EXCEPTION 'downgrade_blocked: reconciliation_run has rows';
  END IF;
END
$$;

DROP POLICY IF EXISTS reconciliation_run_retention ON reconciliation_run;
DROP POLICY IF EXISTS reconciliation_run_worker_select ON reconciliation_run;
DROP POLICY IF EXISTS reconciliation_run_tenant ON reconciliation_run;
DROP POLICY IF EXISTS import_row_lineage_tenant ON import_row_lineage;
DROP POLICY IF EXISTS import_source_fingerprints_tenant ON import_source_fingerprints;

DROP TRIGGER IF EXISTS reconciliation_run_immutable_trg ON reconciliation_run;
DROP FUNCTION IF EXISTS reconciliation_run_write_guard();

DROP FUNCTION IF EXISTS app_expire_reconciliation_runs(timestamptz, integer);

DROP TABLE IF EXISTS reconciliation_run;
DROP TABLE IF EXISTS import_row_lineage;
DROP TABLE IF EXISTS import_source_fingerprints;
