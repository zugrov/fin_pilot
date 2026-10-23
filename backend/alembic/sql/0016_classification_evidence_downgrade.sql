DO $$
BEGIN
  IF EXISTS (
    SELECT 1
    FROM cash_transactions
    WHERE classification_rule_id IS NOT NULL
    LIMIT 1
  ) THEN
    RAISE EXCEPTION 'downgrade_blocked: classification evidence on cash_transactions';
  END IF;
END $$;

DROP INDEX IF EXISTS cash_transactions_classification_rule_idx;

ALTER TABLE cash_transactions
  DROP CONSTRAINT IF EXISTS cash_transactions_classification_rule_fk,
  DROP CONSTRAINT IF EXISTS cash_transactions_rule_evidence_pair_ck;

ALTER TABLE cash_transactions
  DROP COLUMN IF EXISTS classification_rule_version,
  DROP COLUMN IF EXISTS classification_rule_id;

ALTER TABLE classification_rules
  DROP CONSTRAINT IF EXISTS classification_rules_tenant_company_id_uq;
