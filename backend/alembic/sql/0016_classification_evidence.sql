-- FA-R06.2-B3: evidence правила на cash_transactions (без JSONB snapshot).
-- CREATE INDEX без CONCURRENTLY: выполняется внутри транзакции миграции Alembic.

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE classification_rules
  ADD CONSTRAINT classification_rules_tenant_company_id_uq
  UNIQUE (tenant_id, company_id, id);

ALTER TABLE cash_transactions
  ADD COLUMN classification_rule_id uuid NULL,
  ADD COLUMN classification_rule_version integer NULL;

ALTER TABLE cash_transactions
  ADD CONSTRAINT cash_transactions_rule_evidence_pair_ck CHECK (
    (classification_rule_id IS NULL AND classification_rule_version IS NULL)
    OR (
      classification_rule_id IS NOT NULL
      AND classification_rule_version IS NOT NULL
      AND classification_rule_version >= 1
    )
  ) NOT VALID;

ALTER TABLE cash_transactions
  VALIDATE CONSTRAINT cash_transactions_rule_evidence_pair_ck;

ALTER TABLE cash_transactions
  ADD CONSTRAINT cash_transactions_classification_rule_fk
  FOREIGN KEY (tenant_id, company_id, classification_rule_id)
  REFERENCES classification_rules (tenant_id, company_id, id)
  ON DELETE RESTRICT
  NOT VALID;

ALTER TABLE cash_transactions
  VALIDATE CONSTRAINT cash_transactions_classification_rule_fk;

CREATE INDEX cash_transactions_classification_rule_idx
  ON cash_transactions (tenant_id, company_id, classification_rule_id)
  WHERE classification_rule_id IS NOT NULL;
