# FA-R06.1 · Правила управленческого учёта v1 (accepted design)

**Статус:** accepted design, not implemented (2026-10-21)
**База:** `35235738` · зависимости: [MASTER_PLAN.md](MASTER_PLAN.md) FA-R06 / FA-R07
**Связанные нормы:** [accounting-policy.md](../accounting-policy.md), [import-formats.md](../import-formats.md)

Документ фиксирует **правила v1** для двух отчётов управленческого блока: **ОДДС по видам деятельности** и **возрастной анализ дебиторки**. Реализация, миграции и API — в последующих пакетах; здесь только согласованная методология и контракт.

---

## 1. Границы v1

### Входит

| Объект | Содержание v1 |
|--------|----------------|
| **ОДДС** | Денежные потоки по `business_date` в timezone фирмы; разрез **operating / investing / financing**; строка **unmapped**; исключение внутренних и подтверждённых межфирменных переводов; суммы **брутто (с НДС в деньгах)**; флаги полноты по `coverage_through`. |
| **Дебиторка** | Остаток по контрагенту/документу на дату: признанные продажи минус сопоставленные поступления и корректировки; **возрастные корзины** от якорной даты; частичная оплата; явный статус неполных данных. |

### Не входит (FA-R06.2+ / FA-R07)

- Полный **ОПиУ** (начисленные расходы, себестоимость, распределение общих затрат).
- **Управленческий баланс**, капитал, запасы, НЗП, ОС, амортизация.
- **Налоги** (УСН, НДС к уплате, налог на прибыль) — только пометки «деньги брутто» / «выручка ex VAT».
- **Закрытие периода** (`closed`), версии правил после закрытия, пересчёт прошлых месяцев (FA-R06.4).
- Консолидация группы юрлиц сверх уже существующих правил исключения переводов в scope.

---

## 2. Матрица данных

Принцип: **«нет данных» ≠ 0**. Пустой период при полном покрытии → 0; отсутствие источника или покрытия → `unavailable` + quality flag.

### Регистры ядра (текущая схема)

| Регистр | Есть в продукте | Обязательно для v1 | Не хватает для v1 | Примечание |
|---------|-----------------|--------------------|-------------------|------------|
| **CashTransaction** | `business_date`, `direction`, `amount`, `wallet_id`, `category_id`, `status`, `transfer_group_id`, контрагент, `document_number` | `posted`, сумма > 0, дата, кошелёк, направление | Стабильный `direction_code` в импорте → категория; доля операций без `category_id` | ОДДС строится из posted; см. [import-formats.md](../import-formats.md) |
| **CashCategory** | `code`, `cash_flow_section`, `direction` | Секция ∈ {operating, investing, financing, technical} | Единый tenant-справочник кодов импорта → категория | As-is API: секция **`technical`** в `sections[]`; Q5 — не сливать в unmapped до FA-R07 UI |
| **Wallet / OpeningBalance** | anchor, валюта | Active opening для cash_total | — | Без anchor — обороты ОДДС возможны, остаток `unavailable` (как сейчас) |
| **TransferGroup** | `internal`, `intercompany`, `linked` | — | — | Исключение из внешнего ОДДС по правилам [accounting-policy.md](../accounting-policy.md) |
| **RevenueEntry** | `recognition_date`, `entry_type`, `amount_ex_vat`, `amount_inc_vat`, `vat_amount`, контрагент, `document_number`, `status` | `posted`, дата признания, тип sale/return | `due_date` / срок оплаты **нет** | Дебиторка v1: якорь возраста — см. §4 |
| **RevenueCashMatch** | `revenue_entry_id`, `cash_transaction_id`, `amount` | — | UI/API создания и политика частичных match | Только явные связи; авто-зачёт аванса **запрещён** |
| **PaymentMatch** | plan ↔ cash | — | — | **Не** уменьшает дебиторку v1 |
| **PlannedCashEvent** | plan in/out | — | — | Не входят в ОДДС факт |
| **Budget** (version/lines/allocations) | план cash/revenue | — | — | v1 не БДР; plan-fact остаётся отдельно |
| **Obligation** | `receivable`/`payable`, `due_date`, `original_amount` | — | Связь obligation ↔ revenue_entry | v1.1+: срок из obligation; v1 — правило по умолчанию |
| **SourceConnection** | `dataset`, `coverage_through`, `enabled` | Для «полного» факта: coverage ≥ `date_to` | Email/IMAP — вне v1 | Как в `report_service._coverage` |

### Качество (общие флаги v1)

`missing_opening_balance`, `stale_cash_source`, `partial_period`, `missing_revenue_source`, `unclassified_operations`, `vat_basis_unknown`, `reconciliation_difference` — наследуются из [accounting-policy.md](../accounting-policy.md). Отчёт v1 обязан пробрасывать их в `quality_flags`, не скрывая блок.

---

## 3. ОДДС (v1)

### 3.1. Определения

- **Период:** `[date_from, date_to]` включительно по **`business_date`** в **`companies.timezone`** (границы дня — местные).
- **Внешний поток:** posted `CashTransaction`, не исключённые как internal/intercompany (см. `report_service.cashflow_payload` / `group_cashflow_payload`).
- **Сумма в ОДДС:** поле **`amount`** операции (**брутто**, НДС внутри платежа). Выручка ex VAT в ОДДС **не** подставляется.
- **Округление:** `Numeric(20,2)`, half-up до копейки на каждой операции; итоги — сумма округлённых строк (как `money` / `money_str`).

### 3.2. Формулы

Для каждой секции `s ∈ {operating, investing, financing, unmapped}`:

```
ODDS_in(s)  = Σ amount WHERE direction=in  AND section=s AND external
ODDS_out(s) = Σ amount WHERE direction=out AND section=s AND external
ODDS_net(s) = ODDS_in(s) − ODDS_out(s)
```

**Внешний итог:**

```
external_in  = Σ_s ODDS_in(s)
external_out = Σ_s ODDS_out(s)
net_external = external_in − external_out
```

**Остаток денег** на конец периода — **не** часть ОДДС v1 (остаётся в cash summary); при отсутствии opening — не выводить «нулевой» остаток.

### 3.3. Сопоставление категорий и `direction_code`

| Источник | Правило v1 |
|----------|------------|
| Импорт cash | `category_code` → `CashCategory.code` → `cash_flow_section` |
| Пустой / неизвестный код | секция **`unmapped`**, флаг `unclassified_operations` |
| `direction_code` в revenue/budget | Справочник `Direction` (аналитика); **не** подменяет `cash_flow_section` для ОДДС |
| Системные категории | `operating`, `investing`, `financing`, `owner_contribution`, `loan` (см. seed `0003_cash.sql`) |

**Виды деятельности (МСФО-лайт):**

| Секция | Смысл v1 |
|--------|----------|
| **operating** | Операционная деятельность (выручка/поставщики/оплата труда через cash) |
| **investing** | CAPEX, продажа/покупка долгосрочных активов (когда появятся категории) |
| **financing** | Займы, вклад/вывод собственника, **не** выручка |
| **unmapped** | Неклассифицированные операции (обязательно видны в отчёте) |

### 3.4. Исключения

- **Internal transfer** (`TransferGroup.kind=internal`, `status=linked`): обе ноги **не** входят во внешний ОДДС.
- **Intercompany** в scope группы: исключаются пары, если обе firm в `scope_company_ids` (как сейчас).
- **Financing in** (вклад, займ): в секции financing, **не** увеличивают operating in.

### 3.5. Несколько счетов (wallets)

Все **active** wallets фирмы в периметре; операции агрегируются в одну ОДДС фирмы. Drill-down — по `wallet_id` (будущий API), v1 — totals.

### 3.6. Полнота

| Условие | Статус отчёта |
|---------|----------------|
| Нет enabled cash-источника | **нет данных** |
| `coverage_through` < `date_to` | **предварительно** + `partial_period` / `stale_cash_source` |
| Есть unmapped | **предварительно** + `unclassified_operations` (Q2) |
| Покрытие полное, классификация полная | **полно** |

---

## 4. Дебиторка (v1)

### 4.1. Единица учёта

**Строка дебиторки** = `RevenueEntry` с `entry_type=sale` минус `return` и минус **явные** `RevenueCashMatch` (по сумме match, не больше остатка строки).

```
gross_sale    = amount_inc_vat  (sale)
gross_return  = amount_inc_vat  (return)
matched_cash  = Σ RevenueCashMatch.amount для entry
balance(entry) = gross_sale − gross_return − matched_cash  (≥ 0)
```

**Валюта v1:** RUB только. **Авансы** (cash in без match) **не** уменьшают balance других entry автоматически.

### 4.2. Агрегация на дату отчёта `as_of`

В расчёт попадают entry с `recognition_date ≤ as_of` и `status=posted`.
**Корректировки прошлых периодов** (новый return на старую sale) уменьшают balance в периоде признания return.

### 4.3. Возрастные группы

Якорь возраста **`age_base_date`** (v1 по умолчанию — см. §9):

| Корзина | Дней просрочки (включительно) |
|---------|-------------------------------|
| **current** | 0–30 |
| **31_60** | 31–60 |
| **61_90** | 61–90 |
| **over_90** | > 90 |

```
age_days = as_of − age_base_date
```

### 4.4. Нет срока оплаты

В `RevenueEntry` нет `due_date`. **v1:** `age_base_date = recognition_date`.
Если позже появится `Obligation.receivable` с `due_date`, linked к entry — **v1.1** переключит якорь (миграция не обязательна для v1 read-model).

### 4.5. Частичная оплата

Разрешены несколько `RevenueCashMatch` на один entry; сумма match ≤ `amount_inc_vat` sale. Остаток попадает в корзину по `age_base_date`.

### 4.6. Неполные данные

| Условие | Поведение |
|---------|-----------|
| Нет enabled revenue-источника | блок **нет данных**, `missing_revenue_source` |
| `coverage_through` < `as_of` | **предварительно** |
| Есть sale без контрагента | строка «без контрагента», не 0 |
| `vat_basis_unknown` | balance в **gross** с подписью; flag сохраняется |

---

## 5. Эволюция существующего ядра

### Переиспользование (без миграций v1)

| Компонент | Использование |
|-----------|----------------|
| `report_service.cashflow_payload` | ОДДС фирмы за период — **готовый каркас** секций |
| `report_service.group_cashflow_payload` | ОДДС группы в scope |
| `cash_service` / `_internal`, `_paired_inside` | Исключения переводов |
| `report_service.revenue_snapshot` | Контроль покрытия revenue (не подмена AR) |
| `RevenueEntry` + `RevenueCashMatch` | База расчёта дебиторки |
| Полигон `tests/synthetic_polygon/profiles.py` | ORACLE и регрессионные пакеты |

### Новая логика (код, не схема)

- **`receivable_aging_service`** (рабочее имя): read-only агрегация entry + matches + buckets; quality flags.
- **API** as-is: `GET /api/v1/companies/{id}/cashflow` — расширить метаданными v1 (`completeness`); целевой alias `/reports/cash-flow` — FA-R06.1-P3.
- **API** `/reports/receivable-aging` — новый read endpoint (FA-R06.1-P3).

### Таблицы / миграции (не создавать в v1)

| Кандидат | Зачем | Нужна ли в v1 |
|----------|-------|----------------|
| `receivable_aging_snapshots` | Закрытый снимок AR | **Нет** (FA-R06.4) |
| `report_periods` | closed/preliminary | **Нет** |
| `revenue_entry.due_date` | Срок оплаты | **Нет** — default recognition_date |
| Materialized view AR | Производительность | **Нет** — объём beta |

**Главный вариант без миграций:** расчёт AR и статус полноты **на лету** из `revenue_entries` + `revenue_cash_matches` + `source_connections.coverage_through`; ОДДС — уже так. Снимки — только после FA-R06.4.

---

## 6. Независимый ORACLE (полигон, `as_of = 2026-10-31`)

Период ОДДС: **2026-10-01 … 2026-10-31**. Timezone: **Europe/Moscow** (как у полигона).
Профили: **services**, **retail**, **subscription** из [profiles.py](../../backend/tests/synthetic_polygon/profiles.py) — **не** `gap_digest` (не ломает группу **117500 / 46000**).

Дополнительный профиль для насыщенной дебиторки (будущий **`receivable_demo`**, **не** в `ALL_PROFILES`): явные `RevenueCashMatch`, частичная оплата, return — **описан в пакете FA-R06.1-P2**, не меняет групповой ORACLE.

### 6.1. ОДДС ORACLE (ручной, все операции `category_code=operating` → секция operating)

| Профиль | In | Out | Net external | Примечание |
|---------|-----|-----|--------------|------------|
| **services** | 20 000.00 | 3 000.00 | 17 000.00 | cash 12k+8k in, 3k out |
| **retail** | 22 200.00 | 2 500.00 | 19 700.00 | cash 15k + clientbank 7.2k in |
| **subscription** | 4 800.00 | 0.00 | 4 800.00 | 4×1.2k in |

**unmapped:** 0.00 при полном commit импорта с дефолтной категорией operating.

Сверка с [expectations.py](../../backend/tests/synthetic_polygon/expectations.py): `net_cash_flow` совпадает с **net external** за октябрь (все даты профиля ∈ октябре).

### 6.2. Дебиторка ORACLE (gross `amount_inc_vat`, без авто-match)

| Профиль | Продажи (gross) | Возвраты | Matched | **Balance** | current bucket |
|---------|-----------------|----------|---------|-------------|----------------|
| **services** | 12 000 + 6 000 = **18 000** | 0 | **0** | **18 000.00** | весь на 2026-10-31 (age от recognition) |
| **retail** | 28 800 + 7 200 + 1 000 = **37 000** | **3 600** | **0** | **33 400.00** | r1 age 26d (2026-10-05→31), r2 age 20d (2026-10-11→31), return age 11d (2026-10-20→31) |
| **subscription** | 3 × 1 200 = **3 600** | 0 | **0** | **3 600.00** | cash 4 800 > sales — **аванс не зачтён** |

**Проверка retail вручную:** ex VAT net = 28 000 ([expectations.py](../../backend/tests/synthetic_polygon/expectations.py)); gross AR = 33 400 после return 3 600 inc.

**services детализация (recognition → balance):**

- SVC-R-10 (2026-10-10): 12 000.00 — оплата 12 000 (2026-10-05) **не** matchend в полигоне → balance 12 000.
- SVC-R-18 (2026-10-18): 6 000.00 — аванс 8 000 (2026-10-15) **не** matchend → balance 6 000.

---

## 7. Контракт API и экранов (перечень, без реализации)

### ОДДС

| Операция | Права | Ответ |
|----------|-------|--------|
| `GET /api/v1/companies/{company_id}/cashflow?date_from&date_to` | finance read, entitlement | as-is: `sections[]`, `net_external`, `quality_flags`; целевое v1: `completeness: full\|preliminary\|unavailable` (P3) |
| `GET /api/v1/workspaces/{tenant_id}/cashflow?date_from&date_to&company_ids=...` | scope группы | as-is: секции + `excluded_transfer_ids`; `completeness` — P3 |

**Ошибки:** 403 entitlement/email; 404 company; 422 неверный период.
**UI:** таблица секций, drill-down в cash list по `transaction_ids`; баннер при `unclassified_operations`.

### Дебиторка

| Операция | Права | Ответ |
|----------|-------|--------|
| `GET /api/v1/companies/{id}/reports/receivable-aging?as_of` | finance read | `rows[]` {counterparty, document, balance, bucket, age_days}, `totals_by_bucket`, `quality_flags`, `completeness` |
| `POST /api/v1/revenue-cash-matches` | finance write | создание `RevenueCashMatch` (заголовок **`Idempotency-Key`** обязателен); тело: `company_id`, `revenue_entry_id`, `cash_transaction_id`, `amount` |

**Ошибки:** 409 при превышении sum match над entry.
**UI:** heatmap корзин; строки без контрагента; «нет данных» без таблицы нулей.

---

## 8. Матрица тестов и порядок пакетов

| Пакет | Содержание | Критерии приёмки |
|-------|------------|------------------|
| **FA-R06.1-P1** | ORACLE ОДДС октябрь, 3 профиля + профиль **`cashflow_sections`** (не `ALL_PROFILES`); `cashflow_payload` | §6.1; секции нового профиля; internal transfer через **`POST /api/v1/transfers/link`** после импорта |
| **FA-R06.1-P2** | Профиль `receivable_demo` (fixtures only, не ALL_PROFILES) + ORACLE AR | Match частичный, return, аванс не уменьшает чужой entry |
| **FA-R06.1-P3** | API `receivable-aging` + completeness | 403/404; flags; без миграций |
| **FA-R06.1-P4** | UI блоки ОДДС + AR | Состояния нет данных / предварительно / полно |
| **FA-R07.1** (последующий) | Связка с полным комплектом отчётов | Не дублировать формулы v1 |

Запрещено в пакетах v1: подмена 0 вместо unavailable; авто-match аванса; включение plan/budget в факт ОДДС.

---

## 9. Принятые решения и поправки при приёмке (2026-10-21)

### Решения Q1–Q5

| # | Решение |
|---|---------|
| **Q1** | Дебиторка v1 в **gross** (`amount_inc_vat`); net ex VAT — справочная колонка, не замена balance |
| **Q2** | При unmapped > 0 статус отчёта **preliminary** (не «полно с warning») |
| **Q3** | `age_base_date = recognition_date`, пока нет связанного `Obligation.due_date` |
| **Q4** | AR только **company scope**; групповая дебиторка — v2 |
| **Q5** | As-is **`technical`** — отдельная секция в `cashflow_payload`; свёртка в unmapped — улучшение UI (FA-R07), не меняет формулы P1 |

### Поправки 1–6 к черновику proposed

1. Статус документа: **accepted design, not implemented** (реализация — пакеты P2–P4).
2. **§3.6:** unmapped → только **preliminary** (Q2); убрана оговорка «полно с warning».
3. **§6.2:** исправлены возрасты retail по фикстурам (return **11d**, не «−20d»).
4. **§7:** фактические маршруты **`/cashflow`** (компания и workspace); `completeness` — контракт **P3**, не as-is.
5. **§7:** связь продажи с оплатой — **`POST /api/v1/revenue-cash-matches`** + **`Idempotency-Key`** (см. `app/api/v1/revenue.py`).
6. **§8 / P1:** профиль **`cashflow_sections`** вне `ALL_PROFILES`; paired internal transfer — **`POST /api/v1/transfers/link`** (импорт CSV переводы не связывает).

---

## Ссылки

- [MASTER_PLAN.md](MASTER_PLAN.md) — FA-R06, FA-R07
- [DECISIONS.md](DECISIONS.md) — статус accepted FA-R06.1
- [accounting-policy.md](../accounting-policy.md) — инварианты
- [import-formats.md](../import-formats.md) — контракты CSV
