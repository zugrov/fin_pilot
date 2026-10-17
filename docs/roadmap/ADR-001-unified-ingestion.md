# ADR-001. Единый приём данных: транспорт, разбор и проведение

Статус: **принято направление** (архитектурный выбор FA-R00.3, 2026-10-17).
Дата первоначального черновика: 2026-10-17.
Зависит от: FA-R00.1, FA-R00.2 (`DECISIONS.md`, D1–D6).

**Не является:** утверждением DDL, миграций, таблиц в PostgreSQL и
разрешением на реализацию. Имя **`IngestionDelivery`** — проектное имя
логической сущности транспортного слоя; в коде и БД такой модели **нет**.

Контракты, схемы и proposed OpenAPI — черновики FA-R00.4 в
`docs/roadmap/contracts/`; они не подключены к приложению.

## Принятые решения (владелец + ADR)

| ID | Решение |
| --- | --- |
| ADR-001-B | Вариант B: транспортная оболочка **IngestionDelivery** (имя проекта) поверх существующих **ImportBatch** и финансового ядра (`commit_import`, `*_import`, `cash_service`). |
| ADR-001-NO-2ND-LEDGER | Второй параллельный финансовый журнал не создавать. |
| ADR-001-CHANNEL | Канал доставляет байты/конверт; алгоритм проведения общий. |
| ADR-001-DEDUP | Межканальная идентичность — только при доказуемом `external_id`/explicit link; fuzzy merge автоматически не применять. |
| ADR-001-COMPLETENESS | Полнота — отдельный слой (`unknown/claimed/reconciled/closed`); не выводить из max(date) и не приравнивать claim отправителя к сверке. |
| D1–D6 | См. `DECISIONS.md` (профиль услуг, объём D3, вариант C, и т.д.). |

## Проектируемые детали (FA-R00.4 / FA-R02, не DDL)

- Поля конверта доставки, кардинальности, машины состояний — см. `contracts/delivery-contract.md`.
- JSON Schema `ingestion-delivery.schema.json` и примеры для `cash`, `revenue`, `plan`.
- Proposed OpenAPI `ingestion-proposed.openapi.yaml` (маршрутов в приложении нет).
- Минимальное изменение данных: таблица/сущность delivery + nullable `ImportBatch.delivery_id`
  (точные типы колонок — на этапе миграции FA-R02.1 после отдельного разрешения).
- Альтернатива без delivery: расширять только `EmailIngestion` — **отклонено** основным путём (вариант A).

## Внешние TBD (не выбираются агентом)

| Тема | Блокирует |
| --- | --- |
| Конфигурация/размещение 1С (D1) | FA-R03, FA-R11 |
| Контур изоляции пилота A/B (D6) | FA-R10.1 |
| Почтовый провайдер, SPF/DKIM/DMARC | FA-R04 |
| OCR/LLM | FA-R05 |
| Источник истины статей ОПиУ/баланса | FA-R06 |
| Роль закрытия периода | FA-R06.4 |
| Policy snapshot/delta commit, unpost scope | FA-R02.4, владелец |
| Коммит `ops/` в git (G11) | FA-R00.4 / владелец |

Контекст решений владельца:

- профиль проектирования — услуги без склада и производства (D2);
- ближайшая проверка — деньги, выручка, планы и прогноз (D3);
- полный ОПиУ, баланс и дашборды — цель продукта, не текущий объём (D4);
- реальные данные не загружаются, вариант C (D5);
- конфигурация 1С, почтовый провайдер, OCR/LLM, контур пилота и закрытие
  периода — не выбираются в этом ADR.

---

## 1. Фактический текущий путь импорта (as-is)

Ниже — только то, что есть в коде на SHA приложения `0449e8d…`.
Желаемая архитектура vNext **не** описывается как уже существующая.

### 1.1. Границы API и роли

| Шаг | HTTP | Сервис |
| --- | --- | --- |
| Создание источника | `POST /api/v1/companies/{company_id}/sources` | `import_service.create_source` |
| Загрузка файла | `POST /api/v1/companies/{company_id}/imports` | `import_service.receive_import` |
| Preview | `GET /api/v1/imports/{batch_id}/preview` | `import_service.preview_import` |
| Ошибки CSV | `GET /api/v1/imports/{batch_id}/errors` | `import_service.errors_csv` |
| Проведение | `POST /api/v1/imports/{batch_id}/commit` | `import_service.commit_import` |
| Покрытие продаж (ручное) | `POST /api/v1/companies/{company_id}/sources/{source_id}/coverage` | `revenue_service.set_coverage` |
| Синхронизация почты | `POST …/sources/{source_id}/sync` | `mail_service.sync_mailbox` → `ingest_mailbox` |

Маршруты: `backend/app/api/v1/imports.py`.
Проверки: membership (роли `operator` и `billing_manager` отклоняются в `_deny`),
`open_company` с режимом `write`/`read`, CSRF на `commit`.

Допустимые типы источника и форматы заданы в `TYPES` внутри
`import_service` (`file`, `clientbank`, `onec`, `email`; наборы `dataset`:
`cash`, `revenue`, `plan`, `budget`).

### 1.2. Модели данных (PostgreSQL)

Сущности в `backend/app/models/imports.py`:

- `SourceConnection` — привязка канала к `(tenant_id, company_id)`,
  `namespace` (уникален на фирму), `dataset`, `format`, `coverage_through`,
  `authoritative`, `config_redacted` / `encrypted_credentials`;
- `ImportProfile` — параметры разбора на connection (1:1);
- `ImportBatch` — одна загрузка **одного** файла (байтов), `file_hash`,
  `file_storage_key`, статус, счётчики строк;
- `RawImportRow` — строка разбора внутри batch;
- `SourceIdentity` — связь `(namespace, external_id)` → проведённая сущность
  (`canonical_entity_id`, `revenue_entry_id`, `planned_event_id`, `budget_line_id`)
  и `payload_hash`;
- `EmailIngestion` — факт обработки вложения IMAP
  `(connection, uidvalidity, uid, attachment_hash)` → опционально `batch_id`.

Ограничения БД (`backend/alembic/sql/0004_import.sql`):

- `import_batches_file_uq`: уникальность
  `(tenant_id, company_id, connection_id, file_hash)`;
- `source_identities_key_uq`: уникальность
  `(tenant_id, company_id, namespace, external_id)`.

### 1.3. `receive_import` — от байтов до preview

```183:295:backend/app/services/import_service.py
def receive_import(
    session: Session,
    membership: Membership,
    company: Company,
    user: User,
    settings: Settings,
    *,
    connection_id: uuid.UUID,
    content: bytes,
    idempotency_key: str,
    at: datetime,
) -> dict:
    ...
    digest = hashlib.sha256(content).hexdigest()
    ...
    existing = session.scalar(
        select(ImportBatch).where(
            ImportBatch.tenant_id == company.tenant_id,
            ImportBatch.company_id == company.id,
            ImportBatch.connection_id == connection.id,
            ImportBatch.file_hash == digest,
        )
    )
    if existing is not None:
        ...
        return payload
    ...
    lines = _parse(...)  # или _parse_revenue / _parse_plan / _parse_budget
    key = _store(settings, company.tenant_id, digest, content)
    batch = ImportBatch(..., status="validating", ...)
    ...
    # для каждой строки: prepare_* → RawImportRow
    batch.status = "preview_ready"
```

Ключевые свойства as-is:

1. **Идемпотентность HTTP** — `IdempotencyRecord` по ключу клиента и
   отпечатку `canonical_hash(f"{connection.id}:{digest}")`.
2. **Повтор того же файла** на том же connection — возвращается существующий
   `ImportBatch`, новый разбор не создаётся.
3. **Хранение исходника** — `_store`: путь `{tenant_id}/{sha256}` на диске
   (`import_storage_dir`).
4. **Разбор** — доменные читатели в `backend/app/domain/imports/`
   (`read_csv`, `read_xlsx`, `read_clientbank`, `read_revenue_csv`, …).
5. **Подготовка строк** — `prepare_revenue` / `prepare_plan` / `prepare_budget`
   или `_prepare` для cash; дедупликация через `classify_duplicate`
   (`backend/app/domain/imports/dedup.py`).
6. **Почта не проводит** — `mail_service._remember` вызывает тот же
   `receive_import`, затем пишет `EmailIngestion` со статусом `preview`;
   `commit` для почты — только если пользователь проведёт batch вручную.

Фильтр почты as-is: строковое сравнение `message.sender` с `sender` из
`config_redacted`, без SPF/DKIM/DMARC и без привязки к email аккаунта
(`backend/app/services/mail_service.py`, `_remember`).

### 1.4. `commit_import` — проведение в финансовое ядро

```333:411:backend/app/services/import_service.py
def commit_import(...) -> dict:
    ...
    for row in _rows(session, batch):
        if row.proposed_action in {"skip", "review"} or row.duplicate_status in {...}:
            continue
        # revenue / plan / budget → *\_import.create_imported | revise_imported | link_imported
        # cash → _create_row | _revise_row | _link_row
    _apply_statement_coverage(...)
    batch.status = "completed" | "completed_with_errors"
```

Проведение:

- **Cash** — `CashTransaction` (`status="posted"`), `SourceIdentity` с
  `entity_type="cash_transaction"` (`_create_row`, `_identity`).
- **Выручка / план / бюджет** — отдельные модули `revenue_import`,
  `plan_import`, `budget_import` с тем же паттерном identity.
- **Исправление** — `_revise_row` / `revise_imported`: обновление сущности и
  `payload_hash` в `SourceIdentity`, версия транзакции через `_remember_revision`.
- **Связь без новой операции** — `_link_row` / `link_imported`.
- **Отмена операции в UI/API** — `cash_service.void_transaction` (`status="void"`);
  **обратной связи с импортом/unpost delta в коде нет**.

Покрытие as-is: после commit ClientBank `_apply_statement_coverage` берёт
`ДатаКонца` из файла и, если дата больше текущей, пишет
`SourceConnection.coverage_through`. Для продаж — только ручной
`POST …/coverage`.

### 1.5. Дедупликация и «межканальность» as-is

`classify_duplicate` (`dedup.py`): по `(namespace, external_id)` и
`payload_hash` в `SourceIdentity` — статусы `repeated` / `changed` / `new`;
без `external_id` — эвристика `_other_ids`: поиск **другого namespace** с
совпадением wallet, даты, суммы, направления, описания → `linked` / `ambiguous`.

Это **не** доказанная межканальная идентичность: совпадение полей может
дать ложную связь или `ambiguous` → `review` без автоматического слияния.

### 1.6. Чего as-is нет

- HTTP-приёма структурированного пакета 1С;
- scoped machine tokens;
- транспортной сущности «один логический пакет — несколько файлов/chunk»;
- snapshot/delta, tombstone/unpost на уровне импорта;
- `source_instance_id` базы 1С;
- состояний полноты `unknown | claimed | reconciled | closed`;
- автопроведения почты;
- контрольных итогов пакета до commit.

---

## 2. Сравнение вариантов архитектуры

Оба варианта сохраняют **одно финансовое ядро**: существующие
`commit_import` и сервисы `*_import` / `cash_service`, без второго журнала
проводок. Различие — где хранить транспорт и метаданные канала.

### Вариант A. Расширение существующих импортных сущностей

**Идея.** Добавить nullable-поля в `ImportBatch`, `RawImportRow`,
`EmailIngestion`, возможно `SourceConnection`; почтовые и API-метаданные
вешать на batch; многочастность — через связь batch→parent batch или JSONB.

**Меняются (предложение, не миграция):**

| Сущность | Новые поля (пример) |
| --- | --- |
| `ImportBatch` | `channel`, `delivery_idempotency_key`, `client_package_id`, `chunk_index`, `chunk_count`, `transport_status`, `received_at` |
| `RawImportRow` | `source_revision`, `operation` (upsert/unpost) — пока не используются commit |
| `EmailIngestion` | обобщить или дублировать поля для API |
| `SourceConnection` | не обязательно |

**Покрываемые сценарии:**

- один файл через кабинет — **уже**;
- повтор идентичного файла — **уже** (unique file_hash);
- email как сейчас — с доп. полями на batch;
- исправление по `external_id` — **уже** (`changed` → revise).

**Слабо или рискованно:**

- письмо с **несколькими** вложениями: несколько batch без общего родителя;
- «тот же `package_id`, другое содержимое»: конфликт с unique `file_hash`
  (нужен второй ключ, смешение с file-dedup);
- частичный сбой multi-chunk: статус на одном batch не описывает весь пакет;
- незавершённый snapshot: нет агрегата «пакет не закрыт»;
- контрольные итоги на уровне поставки до разбора строк.

**Риски:**

- раздувание `ImportBatch` (смешение «файл для разбора» и «логическая поставка»);
- уникальный индекс `file_hash` остаётся жёстким для API/delta;
- миграция существующих batch без `channel` — обратная совместимость проще,
  но модель остаётся нечёткой.

**Совместимость:** высокая для текущих клиентов API (поля nullable).

**Миграционный путь:** одна аддитивная миграция; старые batch — `channel=file`.

**Эксплуатация:** один объект в UI «импорт = batch»; сложнее объяснить
оператору цепочку «письмо → три файла → один пакет».

### Вариант B. Отдельная транспортная оболочка + существующие партии

**Идея.** Новая сущность **`IngestionDelivery`** (рабочее имя; в коде ещё нет):
логическая поставка по каналу с идентификаторами транспорта, статусом
транспорта, опциональными control totals и ссылками на 1..N `ImportBatch`
(каждый batch — один байтовый артеfact / один проход разбора).

`EmailIngestion` со временем связывается с delivery или поглощается
полями delivery (миграция данных — FA-R02).

**Меняются:**

| Сущность | Роль |
| --- | --- |
| **IngestionDelivery** (новая) | транспорт, авторизация канала, package/chunk, transport status, control totals (claim), связь с connection/company |
| `ImportBatch` | +nullable `delivery_id`; по-прежнему один file_hash и preview/commit |
| `RawImportRow`, `SourceIdentity`, финансовые таблицы | без смены семантики проведения на первом этапе |
| `EmailIngestion` | ссылка на `delivery_id` вместо/вместе с прямым batch |

**Покрываемые сценарии:**

- все сценарии варианта A для одного файла;
- несколько вложений → один delivery, N batch;
- API: один delivery, chunk_index/chunk_count, ack transport отдельно от commit;
- повтор delivery idempotency key без дубля transport;
- конфликт package_id vs content — статус delivery `content_conflict`, batch не commit;
- partial failure — delivery `partially_received`, batch-level ошибки;
- незавершённый snapshot — delivery `incomplete` до закрытия всех chunk.

**Риски:**

- новая таблица и UI/операционная дисциплина;
- нужны правила: когда commit batch разрешён (все chunk? только validated?).

**Совместимость:** старые batch с `delivery_id IS NULL` работают как сейчас.

**Миграционный путь:** FA-R02.1 — таблица + FK; почта и кабинет сначала
создают delivery из одного batch; multi-attach — FA-R02.2+.

**Эксплуатация:** два уровня мониторинга (delivery vs batch); зато проще
расследовать «письмо целиком» и отличать transport от parse/commit.

### Сводная таблица

| Критерий | A — расширить batch | B — delivery + batch |
| --- | --- | --- |
| Второй финансовый журнал | нет | нет |
| Multi-attachment email | слабо | да |
| API chunks / package_id | конфликт с file_uq | да |
| Обратная совместимость | высокая | высокая (nullable FK) |
| Сложность FA-R02 | ниже старт | выше старт, чище модель |
| Риск смешения слоёв | выше | ниже |

---

## 3. Разделение слоёв: что есть и что менять

| Слой | Назначение | As-is в коде | Изменения (рекомендация B) |
| --- | --- | --- | --- |
| **Транспортный пакет** | факт доставки, канал, idempotency transport, chunk, control totals (claim) | частично: `EmailIngestion`; для файла — неявно заголовок HTTP + Idempotency-Key | **новая** `IngestionDelivery` |
| **Вложение / исходный документ** | неизменяемые байты | `file_storage_key`, SHA-256 = `file_hash` | без смены; привязка к batch |
| **Партия разбора** | parse + preview + commit unit | `ImportBatch`, статусы `validating` → `preview_ready` → `committing` → `completed(_with_errors)` | +`delivery_id`; логика commit **без изменения алгоритмов** |
| **Исходная строка** | raw/normalized, validation | `RawImportRow` | позже nullable `operation`, `source_revision` (FA-R02.2+) |
| **Идентичность / ревизия бизнес-события** | `(namespace, external_id)` + `payload_hash` | `SourceIdentity`, `classify_duplicate` | разделить **namespace источника** и **канал доставки** в ADR-002; межканал — только explicit link или review |
| **Проведённый финансовый факт** | деньги, выручка, план, бюджет | `CashTransaction`, revenue/plan/budget tables | не дублировать |
| **Подтверждение полноты** | доверие к периоду/набору | `SourceConnection.coverage_through` + ручной POST coverage | **новая** модель claims (см. §6); не выводить из max(date) |

---

## 4. Сценарии через рекомендуемую модель (вариант B)

Обозначения: **D** = `IngestionDelivery`, **B** = `ImportBatch`.
Commit по-прежнему только через `commit_import(B)`.

| # | Сценарий | Поведение |
| --- | --- | --- |
| 1 | Один файл через кабинет | D создаётся с `channel=ui`, один B, preview → commit. As-is путь сохраняется; D может быть автоматическим с `delivery_id` на B. |
| 2 | То же событие через email и API | Один и тот же **финансовый** результат только если совпали `(namespace, external_id)` и проведение revise/create согласовано. **Разные** D и **разные** B (разный file_hash). Межканальная «та же операция» → `linked`/`review` через `_other_ids` или явное сопоставление; **не** автослияние по fuzzy. |
| 3 | Письмо с несколькими вложениями | Один D на message (message_id + uid), N B по attachment_hash. Transport status D=`received`; каждый B preview отдельно; commit по каждому B независимо. |
| 4 | Повтор идентичного пакета | Transport: idempotency key D → тот же D. Файл: unique `(connection, file_hash)` → тот же B (as-is). |
| 5 | Тот же ID пакета, другое содержимое | D с тем же `client_package_id` но другим aggregate hash → статус D=`content_conflict`, новый B не commit до review; финансы не меняются. |
| 6 | Исправление ранее принятого документа | Новый B (новый file_hash) или delta-строки с тем же `external_id` → `changed` → `revise_*` (as-is). |
| 7 | Отмена проведения и удаление | As-is: `void_transaction` для cash; импорт **не** шлёт unpost. Целевое: строка с `operation=unpost` → FA-R02.2, статус `review` до явного commit; tombstone не из «отсутствия в delta». |
| 8 | Старая ревизия после новой | При commit проверять `payload_hash` / monotonic revision; устаревшая → `superseded` на уровне row, не перезаписывать без review. As-is частично через `changed`; нужно явное правило порядка (FA-R02.2). |
| 9 | Частичный сбой multi-chunk | D=`partially_received`, полученные chunk → B в preview; missing chunk → delivery не `transport_complete`; commit batch не блокирует другие chunk, но **полнота** не `reconciled`. |
| 10 | Незавершённый snapshot | D mode=snapshot, `chunk_count` не достигнут → D=`incomplete`; commit строк snapshot запрещён или только с flag `partial_import` до явного закрытия snapshot (решение FA-R02.4 + владелец). |
| 11 | Противоречие контрольных итогов | Control totals на D сравниваются после parse; mismatch → B=`preview_ready` но delivery flag `control_mismatch`, commit блокируется или только manual override с audit (FA-R02.4). |

---

## 5. Идентичность источника и способ доставки

**As-is:** идентичность бизнес-строки — `(tenant, company, namespace, external_id)`
в `SourceIdentity`. Namespace задаётся на `SourceConnection`, не на базе 1С.
Канал (file/email) в ключ **не** входит.

**Delivery** (transport) не должен становиться частью financial identity.

**Межканальная идентичность:**

- если нет общего стабильного `external_id`, выданного источником истины —
  **не** dedupe автоматически;
- as-is эвристика `_other_ids` (совпадение суммы/даты/описания между namespace)
  → только `ambiguous` / `review` или осознанный `link` оператором;
- для API/email/file одного события: документировать **explicit linking**
  (как `link_imported` / `_link_row`), не fuzzy merge.

**Рекомендация FA-R02.2:** поле `source_entity_id` в normalized payload
и таблица соответствия envelope dataset ↔ `connection.dataset` (G8 из инвентаризации).

---

## 6. Полнота: фирма, источник, набор, период

**As-is (недостаточно для vNext):**

- одна дата `SourceConnection.coverage_through`;
- ClientBank: auto-max `ДатаКонца` на commit;
- продажи: ручной claim через API.

**Целевая модель (проектирование сейчас, реализация FA-R02.4 / FA-R06):**

Измерение: `(company_id, connection_id | source_group, dataset, period)`.

Состояния (регламент HTML §8):

| Состояние | Смысл |
| --- | --- |
| `unknown` | данных не было или срок давности истёк |
| `claimed` | отправитель/оператор заявил полноту (письмо, UI, API field) |
| `reconciled` | контрольные итоги и сверка согласованы |
| `closed` | период закрыт уполномоченным лицом (роль — открытый вопрос) |

Правила:

- **не** выводить `reconciled` из `max(business_date)` или `coverage_through` alone;
- заявление банка/1С/email = максимум `claimed` до сверки;
- для D3 (деньги, выручка, планы) достаточно описать claims для
  `cash` + `revenue`; plan/prognosis используют свои источники без «закрытия месяца».

Новая сущность (кандидат): **`DatasetCoverage`** или JSONB-массив claims
на connection — **не утверждено** до FA-R00.4 (схема) и FA-R02.4 (код).

---

## 7. Границы авторизации каналов

| Канал | As-is | Целевое (без выбора провайдера/1С) |
| --- | --- | --- |
| **Кабинет** | сессия + CSRF + tenant + `open_company` | без изменений принципа |
| **Email** | IMAP credentials на connection; sender string match | подтверждённый email **аккаунта** + SPF/DKIM/DMARC + маршрут на firm/connection; preview-only до FA-R04; **не** пароль API |
| **1С API (будущее)** | нет | machine connection: одноразовый код привязки → scoped token(s) на import/status **конкретной** firm; без cookie владельца; без email как secret |

Проверка entitlement (`paid_through`, слот, email verified) — на сервере
в `receive_import` / future ingest endpoint / jobs (как сейчас через
`open_company` и billing guards).

---

## 8. Неизвестные решения: что проектировать сейчас / что ждёт владельца

| Тема | Можно спроектировать в FA-R00.3–0.4 | Требует решения владельца | Блокер этапа |
| --- | --- | --- | --- |
| Конфигурация/версия/размещение 1С (D1) | общий envelope, поля-заглушки | конкретная конфигурация, образцы выгрузок | **FA-R03**, **FA-R11** |
| Изоляция реального пилота (D6) | ADR «отложено» | A или B перед FA-R10.1 | **FA-R10.1** |
| Почтовый провайдер, SPF/DKIM | модель trust flags | провайдер, DNS | **FA-R04** |
| OCR/LLM | граница «кандидат → confirm» | провайдер, персональные данные | **FA-R05** |
| Источник истины ОПиУ/баланса | карта «TBD» для статей вне D3 | приоритет банк/ОСВ/реестр | **FA-R06** |
| Закрытие периода (`closed`) | состояния в модели | кто подписывает | **FA-R06.4** |
| Snapshot commit policy | варианты в §4 | жёсткое правило | **FA-R02.4** |
| Unpost/tombstone | сценарии §4 | объём для beta | **FA-R02.2** |

FA-R00.3 **не блокируется** открытыми пунктами, если ADR фиксирует TBD
и не подставляет БП 3.0, провайдера и контур пилота.

---

## 9. Рекомендация (принята владельцем 2026-10-17)

**Принят вариант B:** транспортная сущность `IngestionDelivery` (проектное имя) +
существующие `ImportBatch` / `RawImportRow` / `commit_import` /
финансовые сервисы.

**Обоснование:**

1. В коде уже разделён намёк: `EmailIngestion` (transport) vs `ImportBatch` (parse).
2. Unique `file_hash` на connection правильно dedupe **файл**, но мешает
   логическому **пакету** и API chunks без хака в JSONB batch.
3. Финансовые инварианты (Decimal, unavailable, один commit path) сохраняются.
4. Миграция аддитивная: `delivery_id` nullable, старые данные без изменений.
5. Вариант A быстрее на 1–2 задачи, но накапливает технический долг до FA-R11.

**Не делать:** второй журнал проводок; автоматический fuzzy merge между каналами;
утверждать поля миграции до FA-R00.4.

### Последствия для FA-R00.4

- Черновик **имен и связей** сущностей (delivery, coverage claim), без полной JSON Schema.
- Таблица соответствия envelope `dataset` ↔ `SourceConnection.dataset` (G8).
- Матрица capabilities для профиля D2 (услуги): cash, revenue, plan — да; склад — нет.
- Разбивка FA-R02 на задачи с опорой на delivery.
- Решение по `ops/` скриптам (G11) — по-прежнему владелец.

### Последствия для FA-R02

| Задача | Содержание |
| --- | --- |
| FA-R02.1 | Таблица delivery, FK с batch, кабинет и почта создают D; transport idempotency |
| FA-R02.2 | `source_entity_id`, revision/unpost на row; ужесточение порядка ревизий |
| FA-R02.3 | HTTP ingest → delivery (не cookie); machine token — FA-R11, но контракт готовится |
| FA-R02.4 | DatasetCoverage states, control totals, snapshot/chunk gates |

**Тест неизменности:** существующие фикстуры двух фirm и CI на 46d13bf;
новые тесты — parity «UI file → те же итоги, что as-is batch без delivery_id».

---

## Статус ADR и связанные решения

| ID | Статус | Кратко |
| --- | --- | --- |
| ADR-001 направление | **принято** | вариант B, слои, сценарии |
| ADR-001 DDL / код | **не утверждено** | FA-R02 после разрешения |
| D1–D6 | **принято** | `DECISIONS.md` |
| ADR-candidate-import-storage | **отклонено как основной путь** | nullable-поля row — FA-R02.2 |
| DatasetCoverage / delivery DDL | **проект** | `contracts/*`, реализация FA-R02 |
| FA-R00.3 | **local_verified** | принятие направления владельцем |
| FA-R00.4 | **in_progress** | контракты и очередь |

Продуктовый код, миграции, commit/push и сервер этим ADR **не меняются**.
