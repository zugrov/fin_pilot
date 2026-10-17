# FA-R01 · Безопасный сквозной пользовательский путь

Статус этапа: **in_progress** (G0 принят; FA-R01.1 accepted; FA-R01.2 in_progress).

Зависимость: этап **FA-R00** принят (G0) — контракты и ADR, без обязательной
реализации delivery.

## FA-R01.1 · Явный выбор фirm (малый пакет, подробно)

**Цель.** На записывающих экранах пользователь явно выбирает firm; при нескольких
firm без выбора запись недоступна. Убрать silent `companies[0]` на import, sales,
calendar, alerts, wallets.

**Границы.**

- В scope: UI выбора, сохранение `fp_company_id`, блокировка submit без firm.
- Вне scope: billing, новые API, изменение RLS, Playwright (R01.4), balances.csv (R01.2).

**Затрагиваемые файлы (ожидаемо).**

- `frontend/src/pages/ImportPage.tsx`, `SalesPage.tsx`, `CalendarPage.tsx`,
  `AlertsPage.tsx`, `WalletsPage.tsx`
- `frontend/src/lib/companySelection.ts` (новый, по паттерну Forecast/Budgets/Overview)
- `frontend/src/lib/companySelection.test.ts` (vitest)
- Возможно `frontend/src/pages/OverviewPage.tsx` — унификация helper, без смены поведения

**Backend.** Предварительно не требуется: `company_id` в URL/form уже проверяется
сервером. Diff может показать иное — тогда расширить пакет.

**API / миграции.** Нет.

**Тесты.**

- vitest: helper выбора (preferred, picked, list empty)
- регрессия: `npm test`, `npm run build`
- локально две firm в fixture/seed: файл импорта попадает в выбранную firm
- полный backend pytest без изменений

**Критерии приёмки.**

- При 2+ firm запись без выбора невозможна на перечисленных экранах
- Выбранная firm сохраняется в sessionStorage и подставляется после reload
- Существующие интеграционные тесты backend зелёные без правок финансов

**Риски.**

- Расхождение списка firm между страницами → один helper
- Import multipart form: company только из URL path (не из body) — сохранить

---

## Зависимости остальных задач FA-R01

```text
FA-R00 (G0)
  └─ FA-R01.1 контекст firm
       ├─ FA-R01.2 счета и opening (UI; может трогать wallets API только если нет gap)
       ├─ FA-R01.3 формы, idempotency, связи plan/revenue
       └─ FA-R01.4 приёмка пути (зависит от 1.1–1.3; Playwright)
```

| Задача | Зависит от | Блокирует |
| --- | --- | --- |
| R01.1 | FA-R00 | R01.2–R01.4, FA-R02 UI parity |
| R01.2 | R01.1 | R01.4, пилотные шаблоны opening |
| R01.3 | R01.1 | R01.4, FA-R10 ручные обходы |
| R01.4 | R01.1–R01.3 | FA-R02 (сквозной UX) |

**Порядок реализации:** строго R01.1 → R01.2 → R01.3 → R01.4.

---

## FA-R01.2 · Счета и начальный остаток

Задача **in_progress** (принята не целиком): **пакет 1** принят владельцем; **balances.csv** — следующий пакет.

### Пакет 1 · принят (product SHA `93428b758fc581c35b8da933423b11e731a15b90`)

**Приёмка владельцем:** 2026-10-17.

**CI (93428b7):** frontend 83 tests + build; backend 203 pytest PostgreSQL, Ruff, Mypy; run 39038691269.

**Локально:** browser mock wallets-lifecycle A–F (127.0.0.1:8000).

**Staging:** deploy api+frontend finpilot-staging (`127.0.0.1:8090`); read-only smoke Wallets + 7 экранов; write-smoke ООО «Топ»:
create/opening через UI; replay create/opening вернули исходные ID; T-BANK и dashboard (2026-10-01…2026-10-31) без отличий от baseline.

**Приёмочный артефакт на staging (не удалять):** wallet `6337cbaf-5800-4273-8dcd-3c064caaf822` (code `fa-r01-2-smoke-93428b7`); opening `b429046a-7741-40bd-865e-bc2e26e3b22f`; Idempotency-Key create `905d9e37-24bb-4ccf-8821-3d13b8301f66`; opening `f205b4d0-46ff-43b7-bf56-dc8ef2648e25`. Контроль T-BANK `dd1295af-f861-4389-b654-75bdf79aaab0` не изменялся.

Worker/beat на staging при deploy 93428b7 не пересоздавались (образ api c7ff510) — вне доказательств пакета 1.

---

### Пакет 1 · спецификация (историческая)

**Цель (пакет 1).** Безопасное создание счёта и установка active opening из UI; идемпотентность POST
wallet/opening на существующей таблице `idempotency_records`; аддитивное поле `active_opening` в ответе
списка кошельков.

**В scope пакета 1.**

- **Изменение API-контракта (пакет 1):** `POST .../wallets` и `POST .../opening-balance` **требуют**
  заголовок `Idempotency-Key`. Это не обратно совместимо со старыми клиентами без ключа.
  `GET .../wallets` — аддитивно поле `active_opening`.
- Backend: scopes
  `wallet_create`, `wallet_opening`; replay без повторного audit; `duplicate_wallet_code` → 409.
- Frontend: `WalletsPage` — список, создание, opening с подтверждением; TZ фирмы или явный offset;
  сохранение ключа при повторе одного действия.
- Тесты: `test_wallets_idempotency.py`, правки helpers; vitest `walletForm.test.ts`.

**Вне пакета 1 (остаётся в FA-R01.2).**

- `balances.csv` (импорт opening), история `replaced` в UI, wallet access UI, ImportPage wallet picker.
- Приёмка всей FA-R01.2 (`accepted`) — после отдельных пакетов и smoke.

**Миграции.** Нет (IdempotencyRecord уже есть).
