# FA-R03.3 · Provenance и неизменяемый прогон сверки (design)

**Статус:** **proposed (ожидает владельца)** — суженный объём, **без кода** в репозитории.  
**Утверждение этого документа не разрешает** product-код, миграции, деплой, сервер, данные клиента, флаги, секреты и платежи. **Миграции** — только после **отдельного** одобрения владельца с указанием **цели** и **среды** (local/staging/prod).  
**Зависимости:** FA-R03.2 MVP read-only сверки — **accepted_by_owner** 2026-11-04 (SHA `59279ff`); **рекомендуемый порядок:** после FA-R03.4 v1 (см. DECISIONS, блок «порядок этапов»).  
**Не в scope пакета:** сравнение с **ledger** (`cash_transactions`) — отдельная задача **[FA-R03.2d](#fa-r032d-ledger-отдельная-задача)**; сырые `.txt`/`.xls` клиента в Postgres; запись в `DatasetCoverage.evidence`.

---

## 1. Цель

1. Зафиксировать **отпечаток исходника** (файл/доставка) без хранения полного содержимого в БД.
2. Обеспечить прослеживаемость **«строка разбора → нормализованное событие»** (cash/revenue и др. по профилю).
3. Сохранять **неизменяемую запись прогона сверки** FA-R03.2: хеши входов, агрегированные метрики, идентификаторы групп — **без** текстов назначений и названий контрагентов.

Полнота загрузки (`DatasetCoverage`: `claimed` / `reconciled`) и согласование с 1С остаются **разными** понятиями (см. [`FA-R03.2-reconciliation-design.md`](FA-R03.2-reconciliation-design.md)).

---

## 2. Границы (суженный MVP FA-R03.3)

| В scope | Вне scope |
| -------- | ---------- |
| Fingerprint файла/пакета (hash, размер, профиль парсера, период) | Blob исходника в БД |
| Связь `RawImportRow` (или эквивалент) → `SourceIdentity` / проведённая сущность | Пересчёт уже принятого snapshot оплаты |
| Append-only **прогон сверки** bank↔card51 в **отдельной таблице** | JSON в `DatasetCoverage.evidence` |
| Read API для staff/finance (после решения владельца по флагам) | Production-доступ к локальным образцам `var/` |
| RLS по `tenant_id` / `company_id` | UI подтверждения `owner_confirmed` (FA-R03.2+) |

---

## 3. Модель данных (логическая)

### 3.1 Отпечаток исходника (`import_source_fingerprint`)

Один logical файл или part доставки, зарегистрированный при импорте или явной регистрации FA-R03.

| Поле (смысл) | Примечание |
| --- | --- |
| `tenant_id`, `company_id` | RLS |
| `import_batch_id` | FK, nullable если только «внешняя» регистрация для CLI |
| `profile_code` | напр. `ru-bank-clientbank/1.0.0`, `1c-card51-xls/…` |
| `content_sha256` | hash **сырых байт** (или canonical bytes после нормализации кодировки — зафиксировать в профиле) |
| `byte_size` | контроль |
| `parser_version` | версия адаптера |
| `period_from`, `period_to` | опционально, из метаданных разбора |
| `registered_at` | UTC |

**Не хранить:** тело файла, назначения платежей, ФИО/наименования в открытом виде в этой таблице.

Уникальность (предложение): `(company_id, profile_code, content_sha256)` — повторная загрузка того же файла → та же fingerprint-строка, новый batch по политике FA-R02.

### 3.2 Связь строка → событие (`import_row_lineage`)

Мост между разбором и финансовым ядром.

| Поле (смысл) | Примечание |
| --- | --- |
| `tenant_id`, `company_id` | RLS |
| `raw_import_row_id` | FK → `raw_import_rows` |
| `source_identity_id` | FK → `source_identities`, nullable до commit |
| `entity_kind` | `cash_transaction`, `revenue_line`, … |
| `entity_id` | UUID проведённой записи |
| `line_index` | порядок в файле |
| `payload_hash` | hash нормализованного payload строки (как в FA-R02) |
| `linked_at` | момент commit |

**Инвариант:** после успешного commit импорта для каждой проведённой строки batch — одна или явно описанная N:1 связь (агрегация карточки 51 не дублирует cash без правила).

Часть полей может **уже** существовать неявно через `SourceIdentity`; FA-R03.3 формализует таблицу lineage для аудита и сверки, не заменяя `external_id`.

### 3.3 Неизменяемый прогон сверки (`reconciliation_run`)

**Отдельная таблица**, не `DatasetCoverage`.

| Поле (смысл) | Примечание |
| --- | --- |
| `id` | UUID |
| `tenant_id`, `company_id` | RLS |
| `run_kind` | `bank_card_51` (v1) |
| `period_year`, `period_month` | календарный период |
| `input_fingerprints` | JSON: массив `{profile_code, content_sha256, role}` для S1/S2/S3… |
| `input_hashes` | JSON: hash **канонического** представления, использованного движком сверки (без ПII) |
| `metrics` | JSON: `matched_pair`, `group_matched_equivalent`, `not_found_bank`, `chain_errors`, control totals S1/S2/S3 (строки Decimal) |
| `group_refs` | JSON: id групп (дата, direction, amount, kind) — **без** counterparty/purpose |
| `engine_version` | git SHA или semver пакета matching |
| `created_by_user_id` | кто инициировал (staff/finance) |
| `created_at` | UTC |

**Политика:** только `INSERT`; **нет** `UPDATE`/`DELETE` для app-роли (коррекция — новый run с ссылкой `supersedes_run_id`, опционально v2). Retention — см. [решения владельца §7](#7-решения-владельца-вопросы-и-рекомендации).

---

## 4. Миграции (только описание)

Один ревизионный пакет Alembic (номер TBD), SQL в `schema_sql/` по канону проекта:

| Шаг | Содержание |
| --- | --- |
| **M1** | `CREATE TABLE import_source_fingerprint …` + индексы `(company_id, content_sha256)`, `(import_batch_id)` |
| **M2** | `CREATE TABLE import_row_lineage …` + FK на `raw_import_rows`, `source_identities`, partial index на `entity_id` |
| **M3** | `CREATE TABLE reconciliation_run …` + индекс `(company_id, period_year, period_month, created_at DESC)` |
| **M4** | RLS: `ENABLE ROW LEVEL SECURITY`; policies `TO finpilot_app` / `finpilot_worker` — `tenant_id = current_setting('app.tenant_id')::uuid` (и company scope где нужно) |
| **M5** | `GRANT`/`REVOKE`: app — SELECT/INSERT на fingerprint, lineage, run; **нет** UPDATE/DELETE на `reconciliation_run` для app |
| **M6** | Downgrade guard: при наличии строк `reconciliation_run` — блок downgrade (как у карантина почты) |

**Без изменения** схемы `dataset_coverage` в этом пакете.

---

## 5. RLS и безопасность

- Все три таблицы — **tenant-scoped**; finance read/write через существующие проверки `assert_finance_access`.
- Worker может INSERT lineage/fingerprint при commit job; run — только через API/service с session user.
- JSON полей run **валидируется** схемой (max depth/size); запрет ключей `purpose`, `counterparty`, `payer`, `payee` на уровне сериализации.
- Локальный CLI `fa_r03_check` **по умолчанию** не пишет в БД; запись run — только product path после FA-R03.3.

---

## 6. Объём изменений (оценка реализации)

| Слой | Объём |
| --- | --- |
| DDL + RLS | 1 миграция, ~3 таблицы, 6–8 policies |
| Domain | fingerprint при commit/import; builder lineage; serializer run без ПII |
| Services | hook в `import_service` (post-commit); `persist_reconciliation_run()` |
| API | опционально v1: `GET …/reconciliation/runs`, `POST …/reconciliation/runs` (trigger re-run) — **после** решения по флагам |
| Tests | unit serializers + integration RLS + idempotent fingerprint |
| OpenAPI guard | +0…+2 операции (если API в том же пакете) |

**Оценка:** design уже есть; реализация **~5–7 рабочих дней** + приёмка **~2 дня** (синтетика + локальные образцы без staging-клиента).

---

## FA-R03.2d · Ledger (отдельная задача)

| | |
| --- | --- |
| **Цель** | Сверка committed `cash_transactions` ↔ S1/S2; отдельные строки «ledger vs bank» и «ledger vs card». |
| **Зависимость** | FA-R03.3 lineage + стабильный `external_id` / revision (FA-R02.2). |
| **Не блокирует** | приёмку FA-R03.3 и сохранение run bank↔card51. |
| **Evidence** | отдельный `run_kind=ledger_cash` или расширение metrics — **решение при старте 2d**. |

---

## 7. Решения владельца (вопросы и рекомендации — **предложено**, не принято)

| # | Вопрос | Рекомендация |
| --- | --- | --- |
| **Q1** | Где хранить производные метрики сверки? | **Отдельная таблица `reconciliation_run`** (не `DatasetCoverage.evidence`). Coverage остаётся про **полноту загрузки** cash/revenue. |
| **Q2** | Срок хранения записей run и fingerprint? | **24 месяца** rolling для run/metrics; fingerprint — пока существует связанный batch или run. Удаление — job worker + audit log; сырые файлы клиента по-прежнему **не** в БД. |
| **Q3** | Product API сверки вне локального dev-флага FA-R03.2? | **Пока нет.** После FA-R03.3 — только authenticated finance API с tenant entitlement; локальный флаг **снять** или оставить только для `var/` на dev-машине. Production path — fingerprint из **реального** import batch, не hardcoded paths. |
| **Q4** | Ledger-шаг в том же релизе? | **Нет, отдельно FA-R03.2d** после lineage и одного успешного import ClientBank на demo/staging. |
| **Q5** | Кто может создавать run в БД? | Роли finance write + подтверждённый email; staff read-only для audit. |
| **Q6** | Нужен ли UI в FA-R03.3? | **Нет** в MVP пакета; достаточно API/list + экспорт JSON для audit. |

---

## 8. Связанные документы

- [`FA-R03.2-reconciliation-design.md`](FA-R03.2-reconciliation-design.md)
- [`FA-R03.2-owner-acceptance-checklist.md`](FA-R03.2-owner-acceptance-checklist.md)
- [`FA-R03.1-sample-matrix.md`](FA-R03.1-sample-matrix.md)
- [`FA-R03.1-client-request-s9-s11.md`](FA-R03.1-client-request-s9-s11.md) — запрос недостающих образцов клиенту
- [`STAGE_FA-R02-bootstrap.md`](STAGE_FA-R02-bootstrap.md) — idempotency, revision, `DatasetCoverage`

---

## 9. Критерии приёмки FA-R03.3 (черновик)

- [ ] Повторный import того же файла → тот же `content_sha256`, новый batch по правилам FA-R02.
- [ ] После commit batch видна lineage для каждой проведённой строки.
- [ ] Run bank↔card51 сохраняется без ПII; повторный run → новая строка, старая не меняется.
- [ ] RLS: чужой tenant/company не видит run.
- [ ] Downgrade guard при наличии run.
- [ ] Ledger-шаг **не** включён в релиз.
