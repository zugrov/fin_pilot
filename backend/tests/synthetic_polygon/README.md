# Синтетический полигон (FA-R01 / FA-R02)

Вымышленные три компании и фикстуры импорта **только** для `finpilot_test` локально.
Не связаны с `private_samples/` и клиентской 1С.

## Параметры воспроизводимости

| Параметр | Значение |
|----------|----------|
| Seed | `POLYGON_RANDOM_SEED = 0xFA017003` (детерминированные ID в профилях) |
| Период сценариев | 2026-10-01 … 2026-10-31 |
| «Сейчас» в API-тестах | `2026-11-01T06:00:00+00:00` (полный остаток после октября) |

Налоговые параметры — в `profile.meta.json` каждой компании; калькулятор налогов не используется.

## Компании

| Slug | Отрасль | Контракты |
|------|---------|-----------|
| `services` | услуги | balances, cash, revenue, plan, budget |
| `retail` | торговля без склада | + ClientBank 1.03, return в revenue |
| `subscription` | подписки | + partial payment-match plan↔cash |

## Команды

```bash
cd backend

# Пересобрать CSV/txt и manifest.json
uv run python -m tests.synthetic_polygon.build

# Unit: оракул ожиданий
uv run pytest tests/unit/test_synthetic_polygon_expectations.py -q

# Integration: три фирмы, dashboard + group-summary + idempotency + plan match
uv run pytest tests/integration/test_synthetic_polygon.py -q

# Ограничение intraday (cash_total vs обороты)
uv run pytest tests/integration/test_synthetic_polygon_intraday.py -q
```

E2E полигона (отдельный конфиг, clock `2026-11-01`, не трогает group-a…d):

```bash
cd backend && uv run python -m tests.synthetic_polygon.build
cd ../frontend && npm run test:e2e:polygon
```

Перед первым запуском `prepare_polygon` выполняется автоматически из `playwright.polygon.config.ts`.

## Файлы

- `profiles.py` — декларативные строки (источник правды).
- `expectations.py` — независимый пересчёт + ручной ORACLE.
- `emit.py` / `build.py` — запись в `tests/fixtures/synthetic_polygon/`.
- `harness.py` — загрузка через HTTP API в тестах.
