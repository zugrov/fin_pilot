# FA-R03.3 · Пакет реализации (дополнение к design)

**Статус:** **proposed** — только план; код и миграции **не** разрешены этим документом.  
**Базовый дизайн:** [`FA-R03.3-provenance-design.md`](FA-R03.3-provenance-design.md) (proposed, ожидает владельца).  
**Факт main на дату дополнения:** см. `STATE.json` → `updated_at`; FA-R03.2 MVP read-only — **accepted_by_owner** 2026-11-04 (`59279ff`).  
**Текущий этап (не менять без владельца):** `STATE.json` → `current_stage` **FA-R03**, `current_task` **FA-R03.2**; FA-R03.1 — **ждёт образцов** S10/S11.

---

## 1. Цель пакета

Довести от **read-only сверки** (FA-R03.2 CLI/флаги) до **аудируемого** product-контура:

1. **Fingerprint** импортированного файла без хранения тела в БД.
2. **Lineage** «строка разбора → проведённая сущность».
3. (Фаза полного 3.3) **Append-only** запись прогона сверки `bank_card_51` для staff/finance.

**Вне цели:** ledger↔bank (FA-R03.2d), сырое хранение `.txt`/`.xls` в Postgres, запись клиентских путей `var/` на staging.

---

## 2. Фазы и файлы (ожидаемые при одобрении)

### Фаза 3.3-min (первая)

| Слой | Файлы / зоны (ориентир) |
| --- | --- |
| **Миграция** | `backend/alembic/versions/YYYYMMDD_HHMM_fa_r033_min_…py`, зеркало в `schema_sql/` |
| **Модели** | `backend/app/models/import_source_fingerprint.py`, `import_row_lineage.py` (или расширение существующих FA-R02) |
| **Сервис** | hook в `import_service` (post-commit), `fingerprint_service.py` |
| **Тесты** | `backend/tests/.../test_import_fingerprint.py`, RLS integration |
| **OpenAPI** | без новых операций в 3.3-min (или только internal) |

### Фаза 3.3-full (+ reconciliation_run)

| Слой | Файлы / зоны |
| --- | --- |
| **Миграция** | таблица `reconciliation_run`, downgrade guard |
| **Сервис** | `reconciliation_run_service.py`, serializer без PII |
| **API** | `backend/app/api/.../reconciliation.py` — `GET/POST …/reconciliation/runs` (после Q3 design) |
| **Frontend** | список прогонов — **не** в MVP (Q6 design) |

---

## 3. API (контракт черновик)

| Метод | Назначение | Роли | Entitlement |
| --- | --- | --- | --- |
| `GET /api/v1/companies/{id}/import-batches/{batch_id}/fingerprint` | Отпечаток batch | finance read | стандартный tenant |
| `GET /api/v1/companies/{id}/reconciliation/runs` | Список прогонов (метрики без PII) | finance read | TBD post-3.3 |
| `POST /api/v1/companies/{id}/reconciliation/runs` | Запуск сохранения run | finance write + verified email | TBD |

Существующие **cash / import / reports** API **не ломаются**; lineage — дополнительные read-модели.

---

## 4. Миграции (логически)

См. design §4: **M1** fingerprint, **M2** lineage, **M3** reconciliation_run, **M4–M6** RLS/grants/downgrade guard.

**Предусловия окна:** отдельное разрешение владельца на **номер ревизии** и среду (local → staging); **не** в том же окне, что docs-only.

---

## 5. Риски

| Риск | Митигация |
| --- | --- |
| Дублирование identity при re-import | FA-R02 revision + `content_sha256` (design §3.1) |
| Утечка ПИИ в JSON run | Схема serializer, запрет ключей purpose/counterparty (design §5) |
| Рост таблиц run | Retention 24 мес (design Q2 — **DECISION_REQUIRED**) |
| Смешение coverage и run | Не писать метрики сверки в `DatasetCoverage.evidence` |
| Обход RLS в worker | Политики `finpilot_worker` только INSERT lineage |

---

## 6. Тесты (приёмка реализации)

| Уровень | Сценарий |
| --- | --- |
| Unit | canonical hash, serializer run без PII |
| Integration | RLS: чужой tenant → 404/пусто |
| Integration | повторный import того же файла → тот же fingerprint |
| Integration | downgrade guard при наличии run |
| E2E | **не** обязателен в 3.3-min; опционально API list run на полигоне |
| Manual | локально: batch после ClientBank import на finpilot_test |

**CI:** существующий backend/frontend/playwright; новые тесты — в `ci`, без `var/fa-r03-client-samples/` в раннере.

---

## 7. Критерий завершения (Definition of Done)

### 3.3-min

- [ ] После commit импорта в БД есть fingerprint и lineage для проведённых строк.
- [ ] Повторная загрузка байт-идентичного файла — предсказуемая политика duplicate (документирована в API).
- [ ] Нет blob клиента в БД; нет изменения `current_stage` в STATE без владельца.
- [ ] RLS покрыт тестами; OpenAPI guard без сюрпризов.

### 3.3-full

- [ ] Все критерии design §9 выполнены.
- [ ] Product path сохранения run (не только CLI `fa_r03_check`).
- [ ] Документация runbook обновлена **отдельным docs PR**.
- [ ] **Не** включён FA-R03.2d ledger в тот же релиз.

---

## 8. Связь с MASTER_PLAN и DECISIONS

- [MASTER_PLAN.md](MASTER_PLAN.md): FA-R03.3 — provenance и неизменяемый прогон сверки.
- [DECISIONS.md](DECISIONS.md): реальные данные только локально; миграции — отдельное разрешение.
- [ADR-004](ADR-004-accrual-vs-bank-source-precedence.md) (proposed): lineage `entity_kind` согласован с разделением cash vs revenue.

---

## 9. Открытые решения владельца

Перенос из design §7 — без дублирования статуса **accepted**:

- Q1–Q6 в `FA-R03.3-provenance-design.md` остаются **предложениями** до явной записи в DECISIONS.
