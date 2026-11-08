-- Приёмка стенда: выдача оплаченного периода и entitlements без платёжного провайдера.
-- Подстановки заполняет scripts/staging_acceptance.py (@...@).
-- Выполнять ролью finpilot (миграции), один tenant за транзакцию.

-- ===== GRANT =====
BEGIN;

INSERT INTO billing_periods (
  id,
  tenant_id,
  subscription_id,
  start_at,
  end_at,
  interval,
  company_limit,
  monthly_base_snapshot,
  discount_percent,
  paid_amount,
  status,
  created_at
)
SELECT
  '@PERIOD_ID@'::uuid,
  '@TENANT_ID@'::uuid,
  s.id,
  '@PERIOD_START@'::timestamptz,
  '@PERIOD_END@'::timestamptz,
  'month',
  @COMPANY_LIMIT@,
  4000.00,
  0,
  4000.00,
  'active',
  now()
FROM subscriptions AS s
WHERE s.tenant_id = '@TENANT_ID@'::uuid;

UPDATE subscriptions
SET
  company_limit = @COMPANY_LIMIT@,
  current_interval = 'month',
  paid_through = '@PERIOD_END@'::timestamptz,
  status = 'active',
  revision = revision + 1,
  updated_at = now()
WHERE tenant_id = '@TENANT_ID@'::uuid;

INSERT INTO company_entitlements (
  id,
  tenant_id,
  subscription_id,
  company_id,
  active_from,
  active_until,
  status,
  period_id
)
SELECT
  gen_random_uuid(),
  '@TENANT_ID@'::uuid,
  s.id,
  c.id,
  '@PERIOD_START@'::timestamptz,
  '@PERIOD_END@'::timestamptz,
  'active',
  '@PERIOD_ID@'::uuid
FROM subscriptions AS s
INNER JOIN companies AS c
  ON c.tenant_id = s.tenant_id
  AND c.id = ANY (ARRAY[@COMPANY_ID_ARRAY@]::uuid[])
WHERE s.tenant_id = '@TENANT_ID@'::uuid;

UPDATE companies
SET status = 'active', updated_at = now()
WHERE tenant_id = '@TENANT_ID@'::uuid
  AND id = ANY (ARRAY[@COMPANY_ID_ARRAY@]::uuid[]);

COMMIT;

-- ===== ROLLBACK =====
BEGIN;

DELETE FROM company_entitlements
WHERE period_id = '@PERIOD_ID@'::uuid
  AND tenant_id = '@TENANT_ID@'::uuid;

DELETE FROM billing_periods
WHERE id = '@PERIOD_ID@'::uuid
  AND tenant_id = '@TENANT_ID@'::uuid;

UPDATE subscriptions
SET
  company_limit = 0,
  current_interval = NULL,
  paid_through = NULL,
  status = 'awaiting_payment',
  revision = revision + 1,
  updated_at = now()
WHERE tenant_id = '@TENANT_ID@'::uuid;

UPDATE companies
SET status = 'draft', updated_at = now()
WHERE tenant_id = '@TENANT_ID@'::uuid
  AND id = ANY (ARRAY[@COMPANY_ID_ARRAY@]::uuid[]);

COMMIT;
