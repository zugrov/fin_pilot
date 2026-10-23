# FA-R06.2-B3 · Детерминизм и evidence классификации (design only)

**Режим:** только проектирование — **код, миграции, deploy не выполняются** этим пакетом.  
**База:** `origin/main` = `db58f0f3ce37dd55901a51534b887d22b6af7ffe` (последний push: FA-R06.2-B1 idempotency).  
Коммит **B2** (guardrails + compliance) на момент написания — **локально, без push**; B3 опирается на as-is после B1/B2.  
**Последняя миграция в репозитории:** `20261021_0015` (mail quarantine); на staging phase A зафиксирована **`20261019_0014`**.  
**Трассировка пробелов:** [FA-R06.2-spec-compliance.md](FA-R06.2-spec-compliance.md) (**P5**, **E1**).  
**Источники:** ТЗ v2.0 §10, [HTTP_TRANSACTION_BOUNDARY.md](HTTP_TRANSACTION_BOUNDARY.md), [MASTER_PLAN.md](MASTER_PLAN.md), [STATE.json](STATE.json), [DECISIONS.md](DECISIONS.md).

---

## 0. Цель B3

1. **Детерминизм:** при равном `priority` победитель правила воспроизводим (tie-break по stable id); конфликт нескольких правил с разной категорией — **warning**, не silent flip.  
2. **Evidence:** на операции после классификации правилом сохраняются `classification_rule_id`, `rule_version`, при необходимости снимок условий — для аудита, drill-down (FA-R08) и объяснимости.

---

## 1. Детерминизм

### 1.1. As-is: как выбирается правило

**Загрузка правил из БД**

| Путь | Запрос | ORDER BY |
|------|--------|----------|
| Список в API | `list_rules` | `ClassificationRule.priority` **только** |
| Import / preview / apply | `_rule_views` | **нет ORDER BY** |

```1441:1450:backend/app/services/import_service.py
def _rule_views(session, company) -> tuple[RuleView, ...]:
    rows = session.scalars(
        select(ClassificationRule).where(
            ClassificationRule.tenant_id == company.tenant_id,
            ClassificationRule.enabled.is_(True),
            (ClassificationRule.company_id == company.id)
            | (ClassificationRule.company_id.is_(None)),
        )
    ).all()
    return tuple(_as_view(item) for item in rows)
```

**Выбор победителя в домене**

```13:25:backend/app/domain/imports/rules.py
def matching_category(
    rules: tuple[RuleView, ...],
    ...
) -> str | None:
    ordered = sorted((item for item in rules if item.enabled), key=lambda item: item.priority)
    for rule in ordered:
        if _matches(rule.conditions, ...):
            return rule.category_code or None
    return None
```

- `RuleView` **не содержит** `rule_id` — tie-break по id **невозможен** без расширения модели.  
- При **равном `priority`** порядок в `sorted` стабилен относительно **порядка входного tuple**, но tuple приходит из SELECT **без ORDER BY** → порядок зависит от плана PostgreSQL / физического порядка → **недетерминизм между прогонами и окружениями**.  
- ТЗ §10: «first match, tie по stable ID» — **не выполнено** (compliance **P5**).

**Два потребителя одного tuple**

| Путь | Вызов |
|------|--------|
| Import preview/commit | `_prepare` → `matching_category(rules, …)` → `rule_category_id` в normalized payload → `_create_row` / `_revise_row` / `_link_row` |
| Apply / preview posted | `_rule_transaction_outcome` → `matching_category(all_rules, …)` для сравнения с категорией **конкретного** правила |

Оба используют **один** `_rule_views` + **один** `matching_category`, но порядок правил сегодня не зафиксирован — import и apply **согласованы друг с другом только в рамках одного SELECT**, не между деплоями.

**Не в scope B3 (зафиксировать, не смешивать с tie-break):** ТЗ §10 «manual locked → **company rule** → **tenant rule** → unclassified». Сейчас company- и tenant-правила (**`company_id` NULL**) участвуют в одном пуле только по числовому `priority`, без вторичного tier. Изменение tier — отдельное решение (можно B4 или подпункт после B3).

### 1.2. Предложение: единый порядок + tie-break по id

**Правило сортировки (одно для всего продукта):**

```text
ORDER BY priority ASC, id ASC
```

- `id` UUID — lexicographic order PostgreSQL **стабилен** и совпадает с текстовым сравнением строк.  
- Дополнительно (опционально, если позже утвердят tier): `company_id NULLS LAST` между `priority` и `id` — **не включать в B3 без отдельного ADR**.

**Рефакторинг (implementation B3, не в этом документе):**

1. Вынести `load_rule_views(session, company) -> tuple[RuleView, …]` с `.order_by(ClassificationRule.priority, ClassificationRule.id)`.  
2. Использовать в `_rule_views`, `list_rules` (второй ключ `id` для UI).  
3. Расширить `RuleView`: `rule_id: UUID`, `rule_version: int` (из `ClassificationRule.version`).  
4. Заменить `matching_category` → `matching_rule(...) -> MatchResult | None` с полями `rule_id`, `rule_version`, `category_code` (или сохранить `matching_category` как thin wrapper для совместимости тестов).

**Тест на воспроизводимость (новый, B3):**

- `test_matching_tie_break_by_rule_id`: 2+ enabled rules, **одинаковый priority**, разные `id`, условия матчат одну операцию → два прогона `matching_rule` дают **один и тот же** `rule_id`.  
- `test_import_and_apply_same_winner_on_tie`: synthetic polygon / factory — commit import и apply другого правила с тем же priority → та же категория, что у меньшего `id`.  
- Property-style: перестановка порядка INSERT правил **не меняет** победителя (проверка, что ORDER BY в SQL, а не порядок создания).

### 1.3. Conflict warning

**Определение конфликта (предложение):** для одной операции существуют **≥2 enabled** правила с **минимальным** `priority` среди матчей, и **`category_code` различается** (даже если tie-break выбрал одного победителя).

| Место | Нужен warning? | Поведение |
|-------|----------------|-----------|
| **Preview** (`POST …/preview`) | **Да** | Скан без записи; пользователь видит риск до apply |
| **Apply** (`POST …/apply`) | **Да, счётчик** | Apply по-прежнему применяет **одного** победителя (tie-break); конфликтные tx не дублируют apply |
| **Import `_prepare`** | **Quality flag** | В preview import batch: строка/ batch flag `classification_rule_conflict` (не блок commit, если нет других ошибок) |
| **Создание/ PATCH правила** | **Опционально (info)** | Если новое правило создаёт потенциальный конфликт с существующим на том же priority — **200 + warnings** в ответе, не 409 |

**Формат API (preview / apply response, additive):**

```json
{
  "warnings": [
    {
      "code": "classification_rule_conflict",
      "message": "Несколько правил с приоритетом 10 дают разные категории; применено правило с наименьшим id.",
      "priority": 10,
      "rule_ids": ["uuid-a", "uuid-b"],
      "affected_transactions": 3
    }
  ]
}
```

- Поле **`warnings`**: массив объектов; **не** ломает существующие клиенты (optional).  
- **`affected_transactions`**: только в preview/apply aggregate; в import row-level — отдельный код в `review_reason` / quality_flags.

**UI (ClassificationPage, без JSON-таблиц):**

- Под блоком preview: жёлтый текст одной строкой из `warnings[0].message` или «Конфликт правил: N операций — см. приоритеты».  
- Apply-диалог: та же строка перед кнопкой «Применить».  
- Создание правила: toast/inline info, не блокирует submit.

**Audit:** опционально `audit_log` action `classification_rule_conflict_detected` при apply с `affected_transactions > 0` — не обязательно в MVP B3.

### 1.4. Согласованность import и apply

После B3 **одна функция** `ordered_rule_views(session, company)` + **один** `matching_rule` — вызываются из:

- `_prepare` (import),  
- `_rule_transaction_outcome` / preview / apply,  
- unit-тесты домена без БД (tuple с заданным порядком).

Критерий: для фикстуры «две операции, два правила same priority» import commit и последующий apply **не расходятся** по категории.

---

## 2. Evidence на операции

### 2.1. Что хранить (минимум ТЗ §10)

| Поле | Назначение |
|------|------------|
| `classification_rule_id` | Какое правило назначило категорию |
| `classification_rule_version` | Версия правила **на момент** применения |
| `classification_conditions_snapshot` (optional JSONB) | Копия `conditions_json` на момент apply/import; нужна если правило удалили или условия менялись |

Инварианты:

- Заполняется **только** при `classification_origin = 'rule'`.  
- При **manual** classify — **NULL** (origin manual, evidence пустой).  
- При **none** — NULL.  
- `category_id` остаётся источником истины для отчётов; evidence — объяснение «почему».

### 2.2. Варианты хранения A / B / C

| Критерий | **A) Колонки на `cash_transactions`** | **B) `classification_evidence` (1:1 или 1:N)** | **C) Только `transaction_revisions.previous` JSONB** |
|----------|----------------------------------------|-----------------------------------------------|------------------------------------------------------|
| **Миграция** | `ALTER TABLE cash_transactions ADD …` + FK `(tenant_id, classification_rule_id)` | Новая таблица + FK на tx и rule; RLS policy | Расширить JSON в `_remember_revision` без DDL |
| **RLS** | Те же policies, что у `cash_transactions` | Отдельная policy `tenant_id = app_tenant()` | Уже на `transaction_revisions` |
| **Downgrade guard** | `RAISE` если любая строка с non-null `classification_rule_id` | `RAISE` если есть строки evidence | Слабый guard (исторические JSON) |
| **454+ pytest** | Низкий риск: nullable колонки, default NULL; обновить factory asserts | Средний: новая таблица в TRUNCATE conftest | Средний: меняется форма revision — grep `previous` |
| **Объём данных** | 3 колонки на каждую tx | Отдельная строка на каждое rule-применение | Только при revision (import apply создаёт revision не всегда) |
| **FA-R08 drill-down** | **O(1)** в GET transaction / list | JOIN | Нужен «текущий» snapshot — парсить последнюю revision |
| **Import create row** | Запись при insert | Insert evidence row | Нет revision на create — **нет evidence** |
| **Правило удалено** | FK `ON DELETE SET NULL` + snapshot JSONB | То же | Snapshot в старых revisions |

**Рекомендация design (для решения владельца):** **вариант A** — nullable колонки + optional `classification_conditions_snapshot jsonb` на `cash_transactions`.  
Причины: прямой read для UI/отчётов, минимальные JOIN, согласовано с существующим `classification_origin` / `locked_classification`, проще RLS.

**Вариант B** — если понадобится **история** нескольких rule-apply на одну tx (сейчас apply skip categorized — не нужно).  
**Вариант C** — **не достаточен** alone: `_create_row` не вызывает `_remember_revision`; evidence теряется на первичном import.

### 2.3. Жизненный цикл по событиям

| Событие | category | origin | evidence |
|---------|----------|--------|----------|
| Import create с rule match | rule category | `rule` | rule_id + version (+ snapshot) |
| Import revise, not locked | может обновиться | `rule` if rule_category | обновить evidence |
| Import revise, **locked** | не меняется | manual | без изменений |
| `POST …/classify` | manual | `manual` | **очистить** rule_id, version, snapshot |
| `POST …/apply` | rule | `rule` | записать победителя apply (конкретное правило диалога, если совпало с global winner) |
| PATCH rule (version++) | — | — | **старые tx** сохраняют старый `classification_rule_version` / snapshot |
| Disable / delete rule | category остаётся | `rule` | id → NULL если DELETE SET NULL; snapshot остаётся |
| Void tx | — | — | revision хранит previous; evidence на voided row можно не трогать |

**Apply конкретного правила:** evidence = **это** правило (id + version на момент apply), даже если global tie-break выбрал бы другое — `_rule_transaction_outcome` уже отсекает «не winner». Evidence должно совпадать с применённым правилом.

### 2.4. Backfill

| Стратегия | Описание |
|-----------|----------|
| **Без backfill (рекомендуется для B3)** | Существующие `classification_origin='rule'` остаются с NULL evidence; UI: «Правило не зафиксировано (данные до обновления)» |
| **Best-effort backfill** | Только если одно enabled rule на tenant+company матчит tx **и** category совпадает — проставить id (риск ошибки при equal priority) — **не рекомендуется** без tie-break |
| **Mandatory backfill** | Требует audit trail, которого нет — **отклонить** |

Отображение без backfill:

- API `GET transaction`: `classification_evidence: null | { rule_id, rule_version, conditions_snapshot, status: "recorded" | "legacy_unknown" }`.  
- `legacy_unknown` если `origin=rule` и `rule_id IS NULL`.

---

## 3. Пакет реализации B3 (чеклист для следующего scope)

### 3.1. Файлы (ожидаемые изменения)

| Слой | Файлы |
|------|--------|
| Domain | `backend/app/domain/imports/rules.py` — `MatchResult`, `matching_rule`, conflict scan helper |
| Service | `backend/app/services/import_service.py` — ORDER BY, evidence write, warnings in preview/apply |
| Service | `backend/app/services/cash_service.py` — classify clears evidence; `_remember_revision` optional extra keys |
| Models | `backend/app/models/cash.py` — новые поля |
| API | `backend/app/api/v1/rules.py`, serializers в payloads transaction |
| Alembic | `backend/alembic/sql/0016_classification_evidence.sql`, `0016_classification_evidence_downgrade.sql`, `versions/20261022_0016_classification_evidence.py` |
| Frontend | `ClassificationPage.tsx` — warning line; `api.ts` types для `warnings` |
| Docs | обновить [FA-R06.2-spec-compliance.md](FA-R06.2-spec-compliance.md) **P5**, **E1** → «есть» |

### 3.2. API (additive)

| Endpoint | Изменение |
|----------|-----------|
| `POST /rules/{id}/preview` | + `warnings[]`; опционально `winner_rule_id` в matches |
| `POST /rules/{id}/apply` | + `warnings[]` |
| `GET/PATCH transaction` payloads | + `classification_evidence` block |
| `POST …/classification-rules` | optional `warnings[]` on create (info) |

Без breaking changes; HTTP boundary — один request txn ([HTTP_TRANSACTION_BOUNDARY.md](HTTP_TRANSACTION_BOUNDARY.md)).

### 3.3. Миграция (черновик)

**Revision:** `20261022_0016` (номер уточнить по head на день merge).

**Up (`0016_classification_evidence.sql`):**

- `ALTER TABLE cash_transactions ADD COLUMN classification_rule_id uuid NULL`  
- `ADD COLUMN classification_rule_version integer NULL`  
- `ADD COLUMN classification_conditions_snapshot jsonb NULL`  
- FK `(tenant_id, classification_rule_id) REFERENCES classification_rules (tenant_id, id) ON DELETE SET NULL`  
- CHECK: `(classification_origin != 'rule') OR (classification_rule_id IS NOT NULL)` — **только для новых записей после deploy**; legacy rows exempt → CHECK **не использовать**; enforce в application layer  
- Optional index `(tenant_id, classification_rule_id) WHERE classification_rule_id IS NOT NULL`

**Downgrade guard:**

```sql
IF EXISTS (SELECT 1 FROM cash_transactions WHERE classification_rule_id IS NOT NULL LIMIT 1) THEN
  RAISE EXCEPTION 'downgrade_blocked: classification evidence on cash_transactions';
END IF;
```

### 3.4. Тесты (новые / расширенные)

| Тест | Файл |
|------|------|
| Tie-break by id (domain) | `backend/tests/unit/test_classification_rules_match.py` (новый) |
| Tie import = apply | `backend/tests/integration/test_classification_rule_apply.py` |
| Preview/apply warnings | `backend/tests/integration/test_classification_rule_apply.py` |
| Evidence on import + apply | `backend/tests/integration/test_cashflow_classification_polygon.py` |
| Manual classify clears evidence | `backend/tests/integration/test_cash.py` |
| Locked + import I9 | `backend/tests/integration/test_import_api.py` |
| Migration up/down guard | `backend/tests/integration/test_migration_classification_evidence.py` (паттерн balances) |
| Frontend warning string | `frontend/e2e/classification-polygon.spec.ts` (optional) |

Полный прогон: backend pytest (целевой baseline **454+** на head B1/B2), ruff, mypy; frontend unit; classification E2E.

### 3.5. Риски

| Риск | М mitigation |
|------|----------------|
| Legacy rows `origin=rule` без evidence | `legacy_unknown` в API; без backfill |
| FK rule delete | SET NULL + snapshot JSONB |
| Нагрузка preview (conflict scan) | O(rules × sample tx) — тот же scan что preview; лимит matches уже есть |
| Расхождение import/apply | Единый ORDER BY + unit test |
| Downgrade на staging с evidence | Guard + release note |

### 3.6. Критерий завершения B3 (implementation)

1. Compliance **P5**, **E1** — «есть» с тестами.  
2. Два правила same priority → детерминированный winner в unit + integration.  
3. Preview возвращает warning при category conflict.  
4. Новые rule-классификации (import + apply) пишут evidence; manual classify очищает.  
5. CI green на SHA B3; classification E2E green; миграция 0016 с guard.

**DoD deploy (B3b):** применение миграций **`20261021_0015` + `20261022_0016`** на staging — **отдельный план** (staging на момент B3: **`20261019_0014`**). В пакете B3 **миграция на staging не выполняется**, deploy и workflows не меняются.

---

## 4. Вне scope B3 (B4 и далее)

| Тема | Пакет |
|------|--------|
| Условия **equals**, **wallet**, **source** | B4 |
| **POST tenant-wide** rules (`company_id` null) | B4 |
| Tier **company before tenant** при равном priority | B4 / ADR |
| Bulk **reclassify** / mass undo apply | B0 (миграция journal) |
| Regex conditions | вне beta (ТЗ) |

---

## 5. Git / docs status (на момент design)

- `origin/main`: `db58f0f3…` (B1).  
- Локально не в push: B2 (tests, UI, STATE, compliance), **этот файл B3-design**.  
- Код продукта для B3 **не менялся**.

---

## Вопрос владельцу

1. **Evidence:** подтверждаем **вариант A** (колонки + optional JSONB snapshot на `cash_transactions`)?  
2. **Миграция `20261022_0016`** (или следующий номер после 0015): **разрешена** для B3 implementation после accept design?  
3. **Conflict warning** на create rule — только info, без блокировки: согласны?  
4. **Backfill** — принимаем **без backfill** + `legacy_unknown` в UI?
