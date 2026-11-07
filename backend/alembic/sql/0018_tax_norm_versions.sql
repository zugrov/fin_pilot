-- P1a: общий справочник версий налоговых норм (не при tenant).
-- btree_gist уже включён в 0002_billing.sql — EXCLUDE по daterange без нового расширения.

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

CREATE TABLE tax_norm_versions (
  id uuid PRIMARY KEY,
  valid_from date NOT NULL,
  valid_to date NULL,
  status text NOT NULL CHECK (status IN ('confirmed', 'needs_review')),
  source_url text NOT NULL,
  verified_at timestamptz NOT NULL,
  verified_by text NULL,
  notes text NULL,
  usn_vat_exemption_threshold_rub numeric(20, 4) NULL,
  special_rate_base_5_cap_base_rub numeric(20, 4) NULL,
  special_rate_base_7_cap_base_rub numeric(20, 4) NULL,
  special_rates_deflator numeric(20, 6) NULL,
  vat_rates_general jsonb NULL,
  vat_rates_special jsonb NULL,
  CONSTRAINT tax_norm_versions_valid_range_ck
    CHECK (valid_to IS NULL OR valid_from <= valid_to),
  CONSTRAINT tax_norm_versions_no_overlap
    EXCLUDE USING gist (
      (
        CASE
          WHEN valid_to IS NULL THEN daterange(valid_from, NULL::date, '[)')
          ELSE daterange(valid_from, valid_to, '[]')
        END
      ) WITH &&
    )
);

CREATE INDEX tax_norm_versions_valid_from_idx ON tax_norm_versions (valid_from);
CREATE INDEX tax_norm_versions_valid_to_idx ON tax_norm_versions (valid_to);

GRANT SELECT ON tax_norm_versions TO finpilot_app, finpilot_worker;

-- 2026: ориентиры ADR-003 §4.1; verified_by=editorial, финальное «confirmed» — при приёмке владельцем.
INSERT INTO tax_norm_versions (
  id, valid_from, valid_to, status, source_url, verified_at, verified_by, notes,
  usn_vat_exemption_threshold_rub,
  special_rate_base_5_cap_base_rub,
  special_rate_base_7_cap_base_rub,
  special_rates_deflator,
  vat_rates_general,
  vat_rates_special
) VALUES (
  'a0000000-0000-4000-8000-000000000001',
  '2026-01-01',
  '2026-12-31',
  'confirmed',
  'https://www.nalog.gov.ru/rn95/taxation/taxes/nds_usn/',
  '2026-11-06T00:00:00Z',
  'editorial',
  'сверено редакцией по ссылкам выше, финальное подтверждение — при приёмке владельцем. '
    'Методичка: https://www.nalog.gov.ru/html/sites/www.rn18.nalog.ru/fls/2026dn/2026_0204_UsnNds.pdf',
  20000000,
  250000000,
  450000000,
  1.090000,
  '["22", "10", "0"]'::jsonb,
  '["5", "7"]'::jsonb
);

-- 2027+: черновик — без жёстких сумм; флаг needs_review для баннера в UI.
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
