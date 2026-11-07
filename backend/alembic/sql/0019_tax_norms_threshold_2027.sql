-- P1a: порог освобождения 20 млн (ФЗ 228-ФЗ), версии 2027–2029 и заглушка 2030+.

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '60s';

ALTER TABLE tax_norm_versions
  DROP CONSTRAINT IF EXISTS tax_norm_versions_status_check;

ALTER TABLE tax_norm_versions
  ADD CONSTRAINT tax_norm_versions_status_check
  CHECK (status IN ('confirmed', 'needs_review', 'partially_confirmed'));

DELETE FROM tax_norm_versions
WHERE id = 'a0000000-0000-4000-8000-000000000002';

INSERT INTO tax_norm_versions (
  id, valid_from, valid_to, status, source_url, verified_at, verified_by, notes,
  usn_vat_exemption_threshold_rub,
  special_rate_base_5_cap_base_rub,
  special_rate_base_7_cap_base_rub,
  special_rates_deflator,
  vat_rates_general,
  vat_rates_special
) VALUES (
  'a0000000-0000-4000-8000-000000000003',
  '2027-01-01',
  '2029-12-31',
  'partially_confirmed',
  'https://www.nalog.gov.ru/rn11/news/activities_fts/16668026/',
  '2026-11-07T00:00:00Z',
  'editorial',
  'Порог 20 млн по 228-ФЗ: https://base.garant.ru/414502711/. '
    'Дефлятор 2027 и базы 250/450 млн не заполнены (приказ Минэкономразвития не найден). '
    'Финальное подтверждение — при приёмке владельцем.',
  20000000,
  NULL,
  NULL,
  NULL,
  '["22", "10", "0"]'::jsonb,
  '["5", "7"]'::jsonb
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
  'a0000000-0000-4000-8000-000000000004',
  '2030-01-01',
  NULL,
  'needs_review',
  'https://www.nalog.gov.ru/rn33/news/tax_doc_news/16636398/',
  '2026-11-07T00:00:00Z',
  NULL,
  'График снижения порога по 228-ФЗ (15 млн за доход 2029 г., 10 млн за 2030 г.); '
    'числа для 2030+ не заполнены до проверки редакции.',
  NULL,
  NULL,
  NULL,
  NULL,
  NULL,
  NULL
);
