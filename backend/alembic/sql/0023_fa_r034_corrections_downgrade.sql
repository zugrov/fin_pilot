DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM source_correction_finding LIMIT 1) THEN
    RAISE EXCEPTION 'downgrade_blocked: source_correction_finding has rows';
  END IF;
END
$$;

DROP POLICY IF EXISTS source_correction_finding_tenant ON source_correction_finding;

DROP TABLE IF EXISTS source_correction_finding;
