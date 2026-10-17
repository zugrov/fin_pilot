SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';
LOCK TABLE source_connections IN ACCESS EXCLUSIVE MODE;
ALTER TABLE source_connections DROP CONSTRAINT source_connections_dataset_ck;
ALTER TABLE source_connections ADD CONSTRAINT source_connections_dataset_ck
  CHECK (dataset IN ('cash', 'revenue', 'plan', 'budget', 'balances'));
