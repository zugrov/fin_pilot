# FA-R03.3 · Пакет реализации (дополнение к design)

**Статус:** **accepted design** · пакет **FA-R03.3-min** **слит в main** (`0fc224d`, PR #34, 2026-11-10); **не deployed**, миграция `20261110_0022` **не применена** на стенде/проде.  
**Базовый дизайн:** [`FA-R03.3-provenance-design.md`](FA-R03.3-provenance-design.md) (accepted 2026-11-10, Q1–Q6).  
**Факт main:** `STATE.json` → `fa_r03_3_min`; FA-R03.2 MVP read-only — **accepted_by_owner** 2026-11-04 (`59279ff`).  
**Текущий этап (не менять без владельца / MASTER_PLAN):** `STATE.json` → `current_stage` **FA-R03**, `current_task` **FA-R03.2**; FA-R03.1 — **ждёт образцов** S10/S11.

---

## 1. Цель пакета

Довести от **read-only сверки** (FA-R03.2 CLI/флаги) до **аудируемого** product-контура:

1. **Fingerprint** импортированного файла без хранения тела в БД.
2. **Lineage** «строка разбора → проведённая сущность».
3. **Append-only** таблица прогона сверки `reconciliation_run` (DDL + RLS + SQL retention hook); **запись прогона из сверки** — отдельно (FA-R03.2 / FA-R03.4, см. §2).

**Вне цели:** ledger↔bank (FA-R03.2d), сырое хранение `.txt`/`.xls` в Postgres, запись клиентских путей `var/` на staging.

---

## 2. FA-R03.3-min (принято Q1, реализовано в main)

**В scope 3.3-min (смержено PR #34):**

| Элемент | Статус в коде |
| --- | --- |
| `import_source_fingerprint` + hook post-commit импорта | есть |
| `import_row_lineage` (cash, revenue, plan, budget `entity_kind`) | есть |
| Таблица `reconciliation_run` (append-only, RLS, worker retention SQL) | есть (DDL); **persist из `fa_r03_check` / product path — нет** |
| Миграция `20261110_0022` + roundtrip/downgrade guard | есть |
| Unit: serializer run без PII, RBAC заготовка persist | есть |
| Integration: RLS, hook resilience, lineage импорт, `app_expire_reconciliation_runs` | есть |

**Не вошло в 3.3-min (отдельные задачи):**

| Элемент | Примечание |
| --- | --- |
| Подключение `persist_reconciliation_run` к сверке (CLI/product) | владелец 2026-11-10: вместе с **FA-R03.2 / FA-R03.4** |
| Расписание retention (cron/worker job на 24 мес) | отдельная задача позже; в SQL есть `app_expire_reconciliation_runs` |
| Расширения RLS сверх fingerprint/lineage/run | вне min |
| Read/Write **API** прогонов (`Q3: no-api` на стенде) | FA-R03.3-full / после entitlement |
| **UI** списка прогонов (`Q6: no-ui`) | не MVP |
| Ledger ↔ bank (**FA-R03.2d**) | отдельный релиз (`Q4`) |

**Порядок по design:** **3.3-min** (main) → **FA-R03.4 v1** → **FA-R03.3-full** (product persist + API по решениям).

---

## 3. FA-R03.3-full (следующие файлы / зоны)

| Слой | Файлы / зоны |
| --- | --- |
| **Сервис** | вызов `persist_reconciliation_run` из product/CLI path |
| **API** | `backend/app/api/.../reconciliation.py` — `GET/POST …/reconciliation/runs` (после Q3) |
| **Frontend** | список прогонов — **не** в MVP (Q6) |
| **Jobs** | scheduled `expire_reconciliation_runs` |

---

## 4. API (контракт черновик)

| Метод | Назначение | Роли | Entitlement |
| --- | --- | --- | --- |
| `GET /api/v1/companies/{id}/import-batches/{batch_id}/fingerprint` | Отпечаток batch | finance read | стандартный tenant |
| `GET /api/v1/companies/{id}/reconciliation/runs` | Список прогонов (метрики без PII) | finance read | TBD post-3.3-full |
| `POST /api/v1/companies/{id}/reconciliation/runs` | Запуск сохранения run | finance write + verified email | TBD |

Существующие **cash / import / reports** API **не ломаются**; lineage — внутренний след, без новых публичных операций в 3.3-min.

---

## 5. Миграции

- **Принятая ревизия:** `20261110_0022` (`0022_fa_r033_min_provenance.sql`).
- **Окно применения:** только после отдельного разрешения владельца (local → staging); **после merge в main схема стенда/прода не обновлялась**.

---

## 6. Риски (актуально после min)

| Риск | Митигация |
| --- | --- |
| Дублирование identity при re-import | FA-R02 revision + `content_sha256` |
| Утечка ПИИ в JSON run | serializer + тесты; persist ещё не в product path |
| Рост таблиц run | SQL expire; **job по расписанию — TODO** |
| Provenance hook ломает commit | `begin_nested` + log без PII (тест) |
| Обход RLS | integration tenant A/B |

---

## 7. Тесты (приёмка 3.3-min — выполнено в PR #34)

| ID | Файл | Сценарий |
| --- | --- | --- |
| a | `test_fa_r033_provenance_rls.py` | RLS: tenant B не видит/не меняет fingerprint, lineage, run |
| b | `test_fa_r033_provenance_hook_resilience.py` | сбой provenance после commit не откатывает импорт |
| c | `test_fa_r033_provenance_import.py` | lineage cash + revenue + plan |
| d | `test_fa_r033_reconciliation_retention.py` | `app_expire_reconciliation_runs`, чужой tenant |
| — | `test_fa_r033_provenance_migration.py` | upgrade/downgrade roundtrip + guard |

**CI:** backend / frontend / playwright на head PR #34 — success.

---

## 8. Критерий завершения (Definition of Done)

### 3.3-min

- [x] После commit импорта в БД есть fingerprint и lineage для проведённых строк.
- [x] RLS покрыт integration-тестами.
- [x] Таблица `reconciliation_run` и retention SQL (без product schedule).
- [ ] Deploy / migrate на staging — **ждёт окна владельца**.
- [ ] Product persist run и API — **вне min**.

### 3.3-full

- [ ] Все критерии design §9.
- [ ] Product path сохранения run.
- [ ] Runbook обновлён отдельным docs PR.

---

## 9. Связь с MASTER_PLAN и DECISIONS

- [MASTER_PLAN.md](MASTER_PLAN.md): FA-R03.3; **следующий логичный код:** **FA-R03.4 v1** (коррекции), при готовности min в целевой среде после migrate.
- [OWNER-DECISIONS-2026-11-10.md](OWNER-DECISIONS-2026-11-10.md): Q1 `reconciliation_run` в min; persist и retention schedule — отложены.
- [DECISIONS.md](DECISIONS.md): миграции — отдельное разрешение.
