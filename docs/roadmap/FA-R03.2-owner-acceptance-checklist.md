# FA-R03.2 · чек-лист приёмки (MVP сверки + 2b/2c)

**Цель:** подтвердить read-only сверку S1 ↔ карточка 51 и CLI `fa_r03_check` на **локальных** образцах, без записи в ledger/БД и без ПII в выводе.

**Окружение:** `cd backend && uv sync --group dev` (`xlrd` для `.xls`).

---

## 1. Подготовка (клиентские данные не в git)

- [ ] `var/fa-r03-client-samples/` (сентябрь: S1, S2, S3).
- [ ] `var/fa-r03-client-samples-2026-08/` (август: S1, S3, S13, …; S2 только в `var/` или Downloads, **не** коммитить).
- [ ] В git нет новых `.xls`/`.txt` выгрузок 1С.

---

## 2. CLI · алгоритм FA-R03.2 (раздел **3b**)

```bash
cd backend
python -m app.tools.fa_r03_check ../var/fa-r03-client-samples --month 2026-09
python -m app.tools.fa_r03_check ../var/fa-r03-client-samples-2026-08 --month 2026-08
```

### 2.1 Контрольные итоги и цепочка (разделы 1–2)

| Проверка | Сентябрь | Август |
|----------|----------|--------|
| `ошибок цепочки остатков` | **0** | **0** |
| `итог S1 = S2 = S3` | **совпало** | **совпало** |
| Документов S1 | **219** | **218** |

### 2.2 Сопоставление **3b** (ступень 1 + группы)

| Метрика | Сентябрь 2026 | Август 2026 |
|---------|---------------|-------------|
| `not_found (банк)` | **0** | **0** |
| `matched_pair` | **217** | **214** |
| `group_matched_equivalent` | **1** | **2** |
| `needs_confirmation_groups` | **0** | **0** |
| Групп с несколькими документами | **1** (17.09 in **5300**, bank=2, card=2) | **2** (03.08 и 06.08 in **1080**, bank=2, card=2) |

**Не принято:** `not_found` > 0; разрыв цепочки; S1≠S2≠S3.

Раздел **3** (номер без групп) — справочно; приёмка MVP — по **3b**.

### 2.3 Статусы

- **`needs_confirmation`** — автоматически при разных секциях ОДДС в группе (на текущих образцах **0**).
- **`owner_confirmed`** — только **ручное** подтверждение с причиной и журналом (**не** в MVP; в отчёте API всегда **0**).

---

## 3. API (локально, за флагом)

Маршрут: `GET /api/v1/companies/{id}/reconciliation/bank-card-51?year=&month=`

| Условие | Ответ |
|---------|--------|
| `FA_R03_LOCAL_RECONCILIATION_ENABLED=false` (default) | **404** |
| `app_env` не `development`/`test` (staging/prod) | **404** |
| `company_id` ≠ `FA_R03_LOCAL_RECONCILIATION_COMPANY_ID` | **404** |
| Флаг вкл., firm совпала, каталог из `FA_R03_LOCAL_SAMPLES_ROOT` | **200** (JSON без названий/назначений) |

Путь к данным **только** из `FA_R03_LOCAL_SAMPLES_ROOT`; обход каталога (symlink вне base) отклоняется.

---

## 4. Юнит-тесты (синтетика)

```bash
cd backend
python -m pytest tests/unit/test_bank_card51_matching.py tests/unit/test_bank_card_reconciliation_paths.py -q
python -m pytest tests/unit/test_fa_r03_reconcile.py tests/unit/test_fa_r03_check_tool.py -q
```

---

## 5. Вне scope приёмки

- Установка набора `ru-bank-clientbank/1.0.0` в tenant/staging.
- Запись сверки в Postgres, ledger, UI подтверждения `owner_confirmed`.
- S10, S11, 8.3.x — см. `FA-R03.1.blocking_inputs`.

---

## 6. Решение владельца

| | |
|--|--|
| **Принято** | Чек-лист выполнен; отдельный docs-коммит `accepted_by_owner` для `fa_r03_2b_2c` / MVP сверки. |
| **Не принято** | Раздел, метрика, факт vs ожидание. |

Дата: **2026-11-04**   Комментарий: **принято** (product SHA `59279ff`, чек-лист агентом + владелец; docs-коммит приёмки).
