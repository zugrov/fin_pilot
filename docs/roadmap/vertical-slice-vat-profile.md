# Вертикальный срез §8 · `vat_basis_unknown` и профиль организации

**Статус:** спецификация реализации (носитель A: dashboard / `revenue_snapshot`).  
**Основание:** [profile-implementation-plan.md](profile-implementation-plan.md) §8, [ADR-003](ADR-003-organization-profile-and-tax-rules.md) §5.

**Контекст main:** P2b (`ca520ec`), OpenAPI **122**.

---

## 1. Где живёт флаг (исходное состояние)

| Слой | Файл | Поведение |
| --- | --- | --- |
| Домен | `assess_revenue()` | Строка с `vat_basis != "net"` или без `amount_ex_vat` → **`vat_basis_unknown`**, gross-сумма, `SOURCE_LABEL`, `metric_basis` = `source`. |
| Сервис | `revenue_snapshot()` | Журнал `revenue_entries` + coverage; после §8 — оверлей профиля. |
| API | `dashboard`, `group-summary`, Telegram digest/bot | Общий `revenue_snapshot`. |

**Вне среза:** дебиторка, бюджет, ОДДС (отдельные флаги).

**Frontend:** `quality_flags` на Обзоре; для §8 — явные подписи в `overview.ts`.

---

## 2. Данные (импорт, ОСВ)

- `SourceConnection.vat_basis` и поля `RevenueEntry` задают «грязность» строк.
- ОСВ напрямую флаг не ставит — только через revenue-факты.
- **Спец. ставки 5/7:** в учёте НДС **входит в цену** (5/105, 7/107); брутто **не** равно «выручка без НДС»; в профиле **не** хранится отдельно 5 или 7 → **`special_rates_5_7` не снимает** `vat_basis_unknown`.

---

## 3. Экран-носитель

**Обзор** (`GET .../dashboard`) — один контракт, e2e/integration, group-summary и digest получают тот же результат через `revenue_snapshot`.

---

## 4. Оверлей профиля (целевое поведение)

### 4.1 Когда включается

Оверлей — **только** для подтверждённой версии профиля, действующей на **месяц строки** (`recognition_date`), при:

| `vat_status` | Оверлей §8 |
| --- | --- |
| **`not_applicable`** | **Да** — снять `vat_basis_unknown` для **этой строки** (брутто трактуется как выручка без НДС, без пересчёта ex-VAT). |
| **`exemption`** (общий случай) | **Нет** — отдельное решение владельца, **не** в §8. |
| **`exemption` + `vat_exemption_article_145` = true** | **Да** — как `not_applicable` (уточнение приёмки). |
| **`special_rates_5_7`** | **Нет** — флаг **остаётся** (см. §2). |
| **`vat_payer`**, **`unknown`**, неподтверждённая версия | **Нет** — прежняя оценка `assess_revenue` (**защита пилота**). |

Контракт **`assess_revenue` без параметров профиля не меняется**; оверлей — тонкий слой **после** него.

### 4.2 Период из нескольких месяцев

1. Для каждого календарного месяца в **[date_from, date_to]** (первое число месяца) и для месяца **каждой** `recognition_date` в выборке — `resolve_profile_for_period` по **одной** загрузке версий (без N+1).
2. Оверлей построчно: по `recognition_date` строки → месяц → версия на этот месяц.
3. Строки без даты: **не применимо** для `revenue_entries` (NOT NULL); если появятся в другом контексте — оверлей **не** применять, оставить оценку `assess_revenue`.
4. Итог: смешанный период — часть строк со снятым флагом (+ информационный признак), часть с **`vat_basis_unknown`**; агрегат суммирует net/ex-vat и брутто по правилам строки.

После полного снятия `vat_basis_unknown` по периоду: `metric_basis` = **`net`**, `label` = **`Выручка без НДС`**, в `quality_flags` добавить **`vat_basis_from_profile`** (информация, **не** ошибка качества).

**Возвраты (`return`):** в брутто-оценке участвуют со знаком минус; оверлей на gross-only return — та же шкала `amount_inc_vat`, что для sale.

### 4.3 `input_revision` и пересчёт снимков

В хеш дашборда (и любой `input_revision`, включающий revenue из `revenue_snapshot`) добавить поле **`revenue_profile`** — компактная строка:

`YYYY-MM:version_id:confirmed` для **месяцев, где к хотя бы одной строке применён оверлей**; месяцы без оверлея не входят.

| Снимок / канал | Пересчёт при смене/подтверждении профиля |
| --- | --- |
| `GET .../dashboard` (`input_revision`) | **Да** |
| `GET .../group-summary` | **Да** (тот же `revenue_snapshot` на фирму) |
| Telegram digest / bot (day, MTD revenue) | **Да** |
| Прогноз (`forecast_service.input_revision`) | **Нет** в §8 (revenue profile не входит) |
| Cashflow `input_revision` | **Нет** |

### 4.4 Frontend (в срезе)

`frontend/src/lib/overview.ts` → `FLAG_TEXT`:

- `vat_basis_unknown` — явное замечание о неизвестной базе НДС.
- `vat_basis_from_profile` — пояснение, что разрез опирается на подтверждённый профиль (НДС не применяется / ст. 145).

### 4.5 Вне среза

Дебиторка, бюджет, ОДДС; пересчёт `amount_ex_vat` из брутто по ставке; общий `exemption` без ст. 145; closed-period политика — только тест на выбор версии по `effective_from`.

---

## 5. Файлы реализации

| Область | Файлы |
| --- | --- |
| Оверлей | `backend/app/domain/org_profile/revenue_vat_overlay.py`, `SaleFact.recognition_date` |
| Сервис | `report_service.revenue_snapshot`, `dashboard_payload` (`input_revision`) |
| Профиль | `list_versions_for_company` + резолв по месяцам в памяти |
| Unit | `test_revenue_vat_profile_overlay.py`, `test_revenue.py` (регресс) |
| Интеграция | `test_org_profile_vat_vertical_slice.py` (dashboard, group-summary, изоляция) |
| UI | `overview.ts`, `overview.test.ts` |

OpenAPI **122** без изменений.

---

## 6. Сценарии приёмки §8

1. **Неподтверждённый профиль** (черновик / `confirmed_at` пусто): gross-only → `vat_basis_unknown`, без `vat_basis_from_profile`.
2. **Подтверждённый `not_applicable`**: те же строки → нет `vat_basis_unknown`, есть `vat_basis_from_profile`, `metric_basis` = `net`, label «Выручка без НДС».
3. **Подтверждённый `special_rates_5_7`**: gross-only → **`vat_basis_unknown` сохраняется**.
4. **Диапазон два месяца, две версии**: октябрь `not_applicable` подтверждён, ноябрь без оверлея / неподтверждён — флаг только по строкам ноября.
5. **Возвраты**: sale + return gross-only при `not_applicable` — сумма и знаки, без ложного net из одной sale.
6. **`group-summary` и digest** — те же флаги/суммы, что dashboard на том же периоде.
7. **Tenant-изоляция**: профиль чужой фирмы не влияет на revenue snapshot.
8. **Polygon / без профиля** — без регресса (как до среза).
9. **Ст. 145**: `exemption` + `vat_exemption_article_145=true`, подтверждено — как п.2.

---

## Связанные документы

- [ADR-003](ADR-003-organization-profile-and-tax-rules.md) §5 (обновлён)
- [accounting-policy.md](../accounting-policy.md)
- [FA-R06.1](FA-R06.1-management-rules-v1.md) §4.6
