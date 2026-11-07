SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

DELETE FROM tax_norm_versions
WHERE id IN (
  'a0000000-0000-4000-8000-000000000003',
  'a0000000-0000-4000-8000-000000000004',
  'a0000000-0000-4000-8000-000000000005'
);

INSERT INTO tax_norm_versions (
  id, valid_from, valid_to, status, source_url, verified_at, verified_by, notes,
  usn_vat_exemption_threshold_rub,
  special_rate_base_5_cap_base_rub,
  special_rate_base_7_cap_base_rub,
  special_rates_deflator,
  vat_rates_general,
  vat_rates_special
) VALUES (
  'a0000000-0000-4000-8000-000000000002',
  '2027-01-01',
  NULL,
  'needs_review',
  'https://www.nalog.gov.ru/',
  '2026-11-06T00:00:00Z',
  NULL,
  'Источники 2027+ расходятся; суммы не заполнены до решения редакции (ADR-003 §4.2).',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL
);

ALTER TABLE tax_norm_versions
  DROP CONSTRAINT IF EXISTS tax_norm_versions_status_check;

ALTER TABLE tax_norm_versions
  ADD CONSTRAINT tax_norm_versions_status_check
  CHECK (status IN ('confirmed', 'needs_review'));
