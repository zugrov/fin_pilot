# Вертикальный срез §8 · `vat_basis_unknown` и профиль организации

**Статус:** разведка (без кода), ветка `docs/vertical-slice-vat-profile`.  
**Основание:** [profile-implementation-plan.md](profile-implementation-plan.md) §8, [ADR-003](ADR-003-organization-profile-and-tax-rules.md) §5.

**Контекст main после P2b:** merge PR #14 → `ca520ec`, CI/e2e зелёные, OpenAPI **122** (`test_http_db_dependency_guard.py`).

---

## 1. Где сегодня живёт флаг

### 1.1 Вычисление (единственная точка продукта)

| Слой | Файл | Поведение |
| --- | --- | --- |
| Домен | `backend/app/domain/revenue.py` → `assess_revenue()` | Если есть хотя бы одна строка с `vat_basis != "net"` **или** `amount_ex_vat is None` → `quality_flags` содержит **`vat_basis_unknown`**, сумма — **gross** (`amount_inc_vat`), подпись **`сумма продаж по данным источника`**, `metric_basis` = **`source`**. Иначе — net-выручка, флаг не ставится. |
| Сервис | `backend/app/services/report_service.py` → `revenue_snapshot()` | Читает `RevenueEntry` за период + покрытие `SourceConnection` (dataset `revenue`), собирает `SaleFact`, вызывает `assess_revenue`. |
| Unit-тест | `backend/tests/unit/test_revenue.py` | `test_unknown_vat_is_not_net_revenue` — эталон контракта флага. |

**Профиль организации в расчёт выручки сегодня не входит** (`get_profile_for_period` используется только в API org-profile).

### 1.2 API, пробрасывающие флаг

| Эндпоинт | Как попадает флаг |
| --- | --- |
| `GET /api/v1/companies/{company_id}/dashboard` | `dashboard_payload()` мержит `revenue_snapshot().quality_flags` в общий `quality_flags` (+ cashflow, cash). |
| `GET /api/v1/workspaces/{tenant_id}/group-summary` | Для каждой фирмы — `revenue_snapshot()`; флаги объединяются в ответ. |
| Косвенно: Telegram digest / bot | `telegram_digest.py`, `telegram_bot.py` вызывают `revenue_snapshot()` (тот же контракт, без отдельного UI). |

Другие отчёты **не выставляют** `vat_basis_unknown` в коде:

- **Дебиторка** (`receivable_aging_service.py`) — в FA-R06.1 описано поведение при флаге, но сейчас флаг **не добавляется** (только `missing_revenue_source`, `missing_counterparty`, …).
- **Бюджет** (`budget_service._revenue_fact`) — при «грязных» строках возвращает `(False, None)` без явного quality flag.
- **ОДДС** (`cashflow_payload`) — свой набор флагов, без НДС-базы выручки.

### 1.3 Frontend

Строка **`vat_basis_unknown` в UI не именована**: нет записи в `frontend/src/lib/overview.ts` → `FLAG_TEXT`, пользователь видит общую фразу *«У отчёта есть замечание к полноте данных.»*

| Экран | Источник данных | Связь с флагом |
| --- | --- | --- |
| **Обзор** (`OverviewPage.tsx`) | `loadDashboard` | `quality_flags` → `qualityNotes()`; выручка — `revenue_label` + `values.revenue` (`revenueDisplay`). |
| **ОДДС** (`CashflowPage.tsx`) | cashflow API | Собственные флаги; не дублирует `vat_basis_unknown` с дашборда, если не пришёл в том же ответе. |
| **Дебиторка** (`ReceivablePage.tsx`) | receivable-aging | Сейчас без `vat_basis_unknown`. |
| Group e2e | `group-summary` | Проверяют `revenue_label` и суммы, не флаг НДС. |

Импорт на фронте: при создании источника в тестах/моках чаще `vat_basis: "net"` (`api.ts`).

---

## 2. Зависимость от данных (ОСВ, импорт)

### 2.1 Импорт и хранение

1. **Подключение источника** (`SourceConnection.vat_basis`: `net` \| `unknown`) — `POST .../sources`, `import_service`, `models/imports.py`.
2. **Строки выручки** (`RevenueEntry.vat_basis`, `amount_ex_vat`, `amount_inc_vat`) — импорт CSV (`domain/imports/revenue_reader.py`, `revenue_import.py`), ручной `POST` revenue API (`revenue_service._checked_amounts`: при `unknown` допустимо пустое `amount_ex_vat`).
3. **Покрытие периода** — без активного revenue-источника и `coverage_through >= date_to` срабатывает `missing_revenue_source` / `partial_period`, а не обязательно `vat_basis_unknown`.

### 2.2 ОСВ и балансы

Прямой связи «ОСВ → `vat_basis_unknown`» **нет**: агрегат смотрит только на журнал **`revenue_entries`**. ОСВ/62 влияют на дебиторку и сверки, но не меняют доменную оценку выручки за период, пока не залиты как revenue-факты с соответствующими полями.

### 2.3 Типичный сценарий флага в пилоте

Источник или строки с `vat_basis: "unknown"` / без `amount_ex_vat` (gross-only выгрузка) при полном coverage → на дашборде выручка с подписью *«сумма продаж…»* и `vat_basis_unknown` в `quality_flags`.

---

## 3. Кандидаты «экран-носитель» (§8)

| # | Носитель | Плюсы | Минусы |
| --- | --- | --- | --- |
| **A. Обзор (dashboard)** | Один вызов `GET .../dashboard`; выручка и quality в одном месте; заметно пользователю; интеграционные тесты (`test_revenue_api.py`, synthetic polygon); **минимальный** путь: только `revenue_snapshot` + тот же JSON-контракт. | UI не показывает имя флага; на блоке «Состояние данных» флаг теряется среди других; смешение cash + revenue flags. |
| **B. Group-summary** | Тот же `revenue_snapshot` на фирму; e2e `group-e-synthetic-polygon`; проверка tenant-scope. | Менее заметен в UI (нет отдельной страницы в продукте); агрегация revenue по фирмам не показывает per-company флаги в UI. |
| **C. Дебиторка** | FA-R06.1 явно требует gross + флаг при неизвестной базе. | **Сейчас флаг не реализован** — для §8 пришлось бы дотянуть AR до спеки; шире срез, чем «приёмка модели». |

**Рекомендация для §8:** **A (Обзор / dashboard API)** — изолированное изменение в `revenue_snapshot` + один интеграционный сценарий «профиль подтверждён → `vat_status` → флаг исчез / остаётся»; фронт можно не трогать для приёмки (достаточно API и при желании — одна подпись в `FLAG_TEXT`).

---

## 4. Предлагаемое минимальное изменение (поведение)

### 4.1 Условие включения профиля

- Вызов `get_profile_for_period(session, tenant_id, company_id, period_month=first_day(date_from))`.
- **Оверлей ADR-003 применяется только если** `resolved.is_confirmed` (см. plan §2, ADR §3).
- Если профиля нет, версия на период **не подтверждена**, или `vat_status` в профиле — `unknown` / черновик → **текущее** поведение `assess_revenue` без изменений (**защита пилота**).

### 4.2 Правила по `vat_status` (подтверждённый профиль)

Ссылка: ADR-003 §5 (матрица `vat_status`).

| `vat_status` (профиль) | Действие относительно `vat_basis_unknown` |
| --- | --- |
| **`not_applicable`** | Снять флаг; интерпретировать период в **согласованной** шкале (для §8 достаточно: не помечать gross-only строки как «неизвестная база»; целевая подпись/база — как для net/учётной политики «НДС не применяется», без выдачи gross за net revenue). |
| **`special_rates_5_7`** (подтверждённый режим спец. ставок) | Снять флаг по ADR (аналог «база определена режимом»); суммы без пересчёта ставки в §8 — только quality/label. |
| **`vat_payer`** | **§5:** ожидается разрез с/без НДС; если в данных есть `amount_ex_vat` и `vat_basis=net` — без флага; если данные по-прежнему только gross/unknown — **флаг сохранять** (профиль не подменяет плохой импорт). |
| **`exemption`** | **§5:** освобождённые операции; для §8 — **не снимать** флаг автоматически только из-за профиля, если строки остаются `unknown`/без ex-VAT; уточнение подписи — отдельный инкремент P4. |
| **`unknown` в профиле** | Как неподтверждённый: без оверлея. |

Реализация: тонкий слой **после** `assess_revenue` (или опциональный аргумент `profile_vat_status`) — не ломать чистый контракт домена для случая «нет профиля».

### 4.3 Что намеренно не входит в срез

- Закрытые периоды / снимок на дату закрытия — только зафиксировать в тесте, что берётся версия по `effective_from` (уже есть `resolve_profile_for_period`).
- Пересчёт `amount_ex_vat` из gross по `vat_default_rate` — **не** в минимуме (риск float; только Decimal при появлении).
- Массовое P4 по всем отчётам.

---

## 5. Файлы и тесты (ожидаемый дифф)

| Область | Файлы |
| --- | --- |
| Логика | `backend/app/domain/revenue.py` (или `backend/app/domain/org_profile/revenue_vat.py` — оверлей), `backend/app/services/report_service.py` (`revenue_snapshot`) |
| Профиль | `backend/app/services/org_profile_service.py` (`get_profile_for_period` — уже есть) |
| Константы | `backend/app/domain/org_profile/constants.py` (`VAT_STATUSES`) |
| Unit | `backend/tests/unit/test_revenue.py` (+ кейсы оверлея), при выносе — `test_revenue_vat_profile.py` |
| Интеграция | новый `test_org_profile_vat_vertical_slice.py` или расширение `test_revenue_api.py`: dashboard до/после confirm + `vat_status=not_applicable` при gross-only sales |
| Регресс | `test_synthetic_polygon.py` / polygon ORACLE — только если меняется label/amount при тех же строках |
| Frontend (опционально) | `frontend/src/lib/overview.ts` — человекочитаемый текст для `vat_basis_unknown`; `overview.test.ts` |
| Документация | этот файл + одна строка в plan §8 «выбран носитель A» |

**OpenAPI:** новых операций нет → счётчик **122** не меняется.

---

## 6. Оценка объёма

| Работа | Оценка |
| --- | --- |
| Оверлей + `revenue_snapshot` + unit | 0,5–1 д |
| Интеграция профиль → dashboard (2–3 сценария) | 1 д |
| Опционально UI-подпись флага + vitest | 0,25 д |
| Приёмка / polygon / owner-checklist §8 | 0,5 д |
| **Итого** | **~2–3 человеко-дня** (один разработчик), без P4 и без дебиторки |

---

## 7. Сценарий приёмки §8 (черновик)

1. Фирма с revenue coverage, строки sale `vat_basis=unknown`, gross only → dashboard: `vat_basis_unknown`, label *«сумма продаж…»*.
2. Подтвердить профиль с `vat_status=not_applicable` (и `effective_from` ≤ периода).
3. Тот же период и те же строки → **нет** `vat_basis_unknown`; подпись/база по таблице §4.2 (зафиксировать ожидаемый `revenue_label` и `metric_basis` в тесте).
4. Снять подтверждение / черновик с `unknown` → снова как в п.1.

---

## Связанные документы

- [ADR-003 · Профиль и налоговые правила](ADR-003-organization-profile-and-tax-rules.md)
- [План внедрения профиля · §8](profile-implementation-plan.md)
- [accounting-policy.md](../accounting-policy.md) — определение `vat_basis_unknown`
- [FA-R06.1 · правила v1](FA-R06.1-management-rules-v1.md) §4.6
