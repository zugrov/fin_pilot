# FA-R01 · Безопасный сквозной пользовательский путь

Статус пакета: **planned** (очередь FA-R00.4). Код не разрешён до G0 и отдельного
разрешения на FA-R01.

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

## FA-R01.2 · Счета и начальный остаток (пакет 1, in_progress)

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
