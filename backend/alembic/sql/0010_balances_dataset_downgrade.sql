SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
LOCK TABLE source_connections IN ACCESS EXCLUSIVE MODE;
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM source_connections WHERE dataset = 'balances') THEN
    RAISE EXCEPTION 'downgrade_blocked: есть подключения с dataset=balances';
  END IF;
END $$;
ALTER TABLE source_connections DROP CONSTRAINT source_connections_dataset_ck;
ALTER TABLE source_connections ADD CONSTRAINT source_connections_dataset_ck
  CHECK (dataset IN ('cash', 'revenue', 'plan', 'budget'));
