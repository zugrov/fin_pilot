-- Снимок seed справочника норм после миграций 0018+0019 (для conftest и сверки с alembic).

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
