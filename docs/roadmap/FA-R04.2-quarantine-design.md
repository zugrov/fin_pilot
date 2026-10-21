# FA-R04.2.2 · Проект постоянного карантина входящей почты

**Статус документа:** `accepted design` + локальная реализация **FA-R04.2.3** (`local_verified`, не deployed).
**База описания кода:** `56a68ec822887a7a8226b88d776beb0665cb3c86` + миграция `20261021_0015`.
**Связанные локальные пакеты (реализованы, не карантин):** [STAGE_FA-R04.md](STAGE_FA-R04.md) — FA-R04.1 gate, FA-R04.2.1 ingress.

Документ **не** является миграцией, API или включением почты. DDL ниже — проект для отдельного решения владельца.

---

## 1. Цель и границы

### Цель

Зафиксировать постоянное хранение **фактов отказа и review** на пути «транспорт → gate → (опционально) preview», чтобы:

- спорные и отклонённые письма не терялись после ответа ingress;
- повторы и конфликты не перезаписывали историю молча;
- расследование не требовало повторного чтения боевого ящика;
- переход в preview оставался только через повторный проход gate (FA-R04.1) и ingress (FA-R04.2.1+).

### В scope проекта

- Одна логическая запись карантина на уникальный ключ `(connection, delivery slot, message_digest)` для исходов **reject** и **review** до preview.
- Метаданные: tenant, company, connection, slot, stage, `reason_code`, digest, timestamps, reviewer, resolution.
- Хранение заголовков только по **allowlist** полей (§3), без полного MIME по умолчанию.
- RLS по tenant/company, те же finance write/paid проверки, что у импорта, для операций «закрыть / эскалировать».
- Идемпотентность записи и immutability `reason_code` после фиксации.
- Контракт будущих API/UI (перечень операций, без реализации).

### Вне scope (явно)

- Создание `import_batches`, `raw_import_rows`, `source_identities`, `cash_transactions`, coverage, outbox.
- `commit_import`, reconcile, автопроведение, подтверждение полноты периода.
- Реальный IMAP/SMTP, DNS/SPF/DKIM/DMARC, выбор провайдера.
- Обход gate: **нет** пути «карантин → preview» без нового `evaluate_mail_admission` + актуальных прав.
- Malware/OCR/LLM, архивы, макросы, HTML/JS в карантине.
- Изменение legacy `poll_mailboxes` / `ingest_mailbox` в этом проекте.

---

## 2. Модель данных (миграция `20261021_0015`, локально)

### Таблица `mail_quarantine_entries`

| Поле | Тип | Ограничения | Назначение |
| --- | --- | --- | --- |
| `id` | `uuid` | PK | Surrogate key |
| `tenant_id` | `uuid` | NOT NULL, FK → tenants | RLS |
| `company_id` | `uuid` | NOT NULL, FK → companies (tenant scope) | RLS |
| `connection_id` | `uuid` | NOT NULL, FK → source_connections (composite tenant+company+connection) | Email-источник |
| `channel` | `text` | NOT NULL, CHECK `channel = 'email'` | Расширение позже только отдельным ADR |
| `uidvalidity` | `bigint` | NOT NULL | Delivery slot (FA-R02 mail key) |
| `uid` | `bigint` | NOT NULL | Delivery slot |
| `message_digest` | `char(64)` | NOT NULL | SHA-256 сырого MIME на границе ingress |
| `message_id_header` | `text` | NULL | Информативно; **не** unique |
| `ingress_stage` | `text` | NOT NULL | `rejected` \| `review` (mirror gate/ingress) |
| `reason_code` | `text` | NOT NULL | Стабильный код FA-R04.1/2.1 + карантин |
| `admission_outcome` | `text` | NOT NULL | `reject` \| `review` |
| `sender_normalized` | `text` | NULL | Только при `admission_outcome=review`; на reject всегда NULL |
| `metadata_allowed` | `jsonb` | NOT NULL DEFAULT `{}` | Allowlist §3 (без subject/From/имён файлов) |
| `slot_content_anomaly` | `boolean` | NOT NULL DEFAULT `false` | `true` на **всех** строках слота при ≥2 digest |
| `status` | `text` | NOT NULL DEFAULT `open` | См. переходы ниже |
| `reviewer_user_id` | `uuid` | NULL, FK → users | Кто закрыл/эскалировал |
| `resolution` | `text` | NULL | `dismissed` \| `escalated` |
| `resolution_note` | `text` | NULL | Краткий комментарий оператора (лимит 500 символов) |
| `created_at` | `timestamptz` | NOT NULL | Момент фиксации |
| `resolved_at` | `timestamptz` | NULL | Закрытие |
| `retain_until` | `timestamptz` | NOT NULL | TTL (§3) |

**Уникальность (идемпотентность):**

```sql
CONSTRAINT mail_quarantine_slot_digest_uq
  UNIQUE (tenant_id, company_id, connection_id, uidvalidity, uid, message_digest)
```

**Индексы (проект):**

- `(tenant_id, company_id, status, created_at DESC)` — список открытых.
- `(tenant_id, connection_id, uidvalidity, uid)` — история слота.
- `(retain_until)` WHERE `status IN ('closed', 'expired')` — job удаления.

### Статусы и переходы

| status | Смысл |
| --- | --- |
| `open` | Требует внимания (review) или зафиксированный reject |
| `closed` | Reviewer закрыл (`dismissed` / `escalated`) |
| `expired` | TTL истёк, allowlist-поля очищены функцией retention |

Допустимые переходы:

```text
open → closed (reviewer + write + paid)
open → expired (retention server function)
closed → expired
```

**Запрещено:** `closed` → `open` без новой доставки; изменение `reason_code` / `ingress_stage` после insert; **тихое** скрытие или удаление строки при новом digest на том же slot.

**Аномалия slot (другой digest):** INSERT новой строки; **все** записи слота остаются; у **каждой** строки слота `slot_content_anomaly = true` (в одной транзакции с insert). Статус `open`/`closed` не сбрасывается автоматически.

**Суточный лимит:** таблица `mail_quarantine_daily_stats` — счётчик `entries_created` и `overflow_count` на `(tenant, company, connection, day_utc)`. Default лимита **`200`** записей/connection/UTC-сутки (`mail_quarantine_daily_entry_limit`): защита от шторма reject/review без скрытия факта переполнения (overflow только в stats, не в entries).

**Нет источника в БД:** `app_record_mail_quarantine` не INSERT; инкремент `mail_quarantine_miss_metrics` (`source_missing`).

**`mail_quarantine_daily_stats` / `mail_quarantine_miss_metrics`:** без полей отправителя (только tenant/company/connection, день UTC или код `reason`, счётчики). Кардинальность ограничена PK: одна строка на connection×день и на connection×reason. Очистка v1 — вместе с tenant-scoped TRUNCATE в integration/tests и при удалении компании (CASCADE по FK); отдельный retention-job для stats **не** включён (строк мало, нет PII).

**RLS (0015):** каждая политика `mail_quarantine_*` с явным `TO finpilot_app` или `TO finpilot_worker`. Обход tenant через `app.mail_quarantine_retention=1` только в политиках **`TO finpilot_worker`**; `finpilot_app` при любом `app.tenant_id` видит только свой tenant. `DELETE` на трёх таблицах для app/worker **не** выдан (REVOKE). `app_expire_mail_quarantine_entries` — **`SECURITY INVOKER`**, owner `finpilot_worker`.

### Что нельзя хранить в БД

- Пароли, OAuth, ключи IMAP, токены, любые заголовки **вне allowlist** (§3).
- Тела вложений, полный MIME, ClientBank/CSV содержимое.
- Неподтверждённые «trusted» флаги из письма (SPF pass в заголовке без transport evidence).
- Сырые IP/HELO цепочки (достаточно enum transport trust на уровне приложения, не персистить в v1).

---

## 3. Хранение содержимого

### Варианты

| Вариант | Плюсы | Минусы |
| --- | --- | --- |
| A. Только метаданные в Postgres | Минимальный риск утечки, проще RLS/backup | Расследование без повторной доставки |
| B. Метаданные + blob store для review | Удобнее расследование | FS ACL, шифрование, GDPR, malware |

### Выбор: **A (метаданные + allowlist JSONB)**

**Обоснование:** reject с стабильным `reason_code` не требует тела. Review опирается на домен отправителя и агрегаты вложений. Полный MIME **не** хранится в v1.

### Allowlist `metadata_allowed` (FA-R04.2.3)

Ingress собирает **только** ключи из списка; subject, raw From, Reply-To и **имена файлов** не сохраняются:

| Ключ JSON | Смысл |
| --- | --- |
| `reason_code` | Код исхода |
| `stage` | `rejected` \| `review` |
| `sender_domain` | Доменная часть единственного From (если извлечён) |
| `attachment_count` | Число вложений |
| `attachment_total_bytes` | Сумма размеров |
| `content_types` | Уникальные MIME (guess по расширению, без имён) |
| `extensions` | Расширения без path/имени |

CHECK: `mail_quarantine_metadata_keys_ok(metadata_allowed)`.

**Audit:** только на resolve (HTTP/UI resolve **не** в FA-R04.2.3).

**Retention:**

- `reject`: `retain_until = created_at + 90 days` (`MAIL_QUARANTINE_REJECT_TTL_DAYS`, default **90** — принято).
- `review`: `retain_until = created_at + 180 days` (default **180** — принято).
- Worker вызывает **`app_expire_mail_quarantine_entries(p_before, p_limit)`** (§4): `SECURITY DEFINER`, owner `finpilot_app` (NOBYPASSRLS), `search_path=public`; caller `finpilot_worker`; обновляет **только** `status='expired'` и `metadata_allowed='{}'`; `reason_code`, slot, digest не меняются. Celery-расписание **не** включено в FA-R04.2.3.

**Файловая система (если v2 blob):** отдельный каталог вне `import_storage_dir`, права `0700`, owner app user, шифрование at-rest (KMS/ключ из `secret_encryption_key`), без path из имени вложения. **v1 проекта — без blob.**

**Шифрование:** at-rest Postgres + TLS; JSONB без секретов.

---

## 4. RLS и права

### Роли приложения

- `finpilot_app` — HTTP API, **NOBYPASSRLS** (как сейчас).
- `finpilot_worker` — retention job, **NOBYPASSRLS**, контекст tenant задаётся явно на строку.

### Политики (проект)

```sql
-- SELECT: membership в tenant + company visible (как companies_for)
USING (
  tenant_id = current_setting('app.tenant_id', true)::uuid
  AND company_id IN (/* app-visible companies for app.user_id */)
);

-- INSERT: только сервис ingress/quarantine writer с уже проверенным binding
-- (реализуется SECURITY DEFINER функцией или trusted service role — отдельное решение;
--  без глобального BYPASSRLS для HTTP)
```

**Чтение списка:** `can_read_finance` для company (owner, finance_manager, accountant, viewer).

**Закрытие review (`closed`):** `can_write_finance` + `assert_company_paid` mode `write` + verified email — те же вызовы, что `assert_finance_access` в [mail_admission_service.py](../../backend/app/services/mail_admission_service.py).

**Запрещено:** глобальный поиск по email отправителя across tenants; «первая фирма» fallback; RLS bypass для support без отдельного ADR.

### Worker и retention-функция

**`app_expire_mail_quarantine_entries(p_before, p_limit)`** (проект):

- Вызывается из Celery/worker под `finpilot_worker` (**NOBYPASSRLS**).
- Внутри: `FOR UPDATE SKIP LOCKED` по индексу `retain_until`; per-row `set_config('app.tenant_id', tenant_id)` перед UPDATE (RLS применяется).
- Разрешённый эффект: `status = 'expired'`, `headers_allowed = '{}'`, `attachment_summary = '[]'`; `reason_code`, slot, digest, anomaly flags **не меняются**.
- Запрещено в функции: DELETE, TRUNCATE, доступ к другим таблицам, `SET ROLE`, bypass RLS.
- Grant: только `finpilot_worker` EXECUTE.

**Запись карантина:** `app_record_mail_quarantine(...)` — `SECURITY DEFINER`, owner `finpilot_app`, trigger запрещает прямой INSERT/UPDATE; EXECUTE `finpilot_app`, `finpilot_worker`. Ingress вызывает из Python при `mail_quarantine_enabled`.

### API (будущее)

- Session user + `X-Tenant-Id`; worker — без публичного HTTP.

---

## 5. Идемпотентность

### Ключ

`(tenant_id, company_id, connection_id, uidvalidity, uid, message_digest)` — совпадает с привязкой [TrustedIngressBundle](../../backend/app/domain/mail_ingress.py) и `mail_delivery_key` в FA-R02.

### Повторная доставка

- **Тот же digest:** INSERT → unique violation → **no-op**, вернуть существующую запись (не обновлять `reason_code`).
- **Тот же slot, другой digest:** новая строка; **обе** сохраняются; `slot_content_anomaly = true`, взаимный `anomaly_peer_id` (см. §2).
- **Конфликт manifest при allow path:** `delivery_conflict` (FA-R02) — **не** карантин preview; отдельная запись карантина с `reason_code=delivery_conflict` если ingress поймал до batch.

### Message-ID

- Хранится в `message_id_header`, **не** участвует в unique. Два разных `(uidvalidity, uid)` с одним Message-ID — две независимые записи (как в тестах FA-R04.2.1).

### Reject/review как факт

- Upsert запрещён. Immutability полей решения. Новый digest на slot — новая строка + anomaly, без удаления старой.

---

## 6. Перепроверка

### Что нужно для повторного рассмотрения

| Сценарий | Достаточно | Нужна новая доставка |
| --- | --- | --- |
| Истёк `paid_through`, был `payment_required` | Повтор ingress после оплаты + **новый** gate at | Да (новый digest или тот же, если transport re-delivers) |
| Viewer пытался отправить | Нет | Да, от verified writer |
| `routing_ambiguous` | Reviewer закрыл dismissed | Новое письмо + gate |
| `forged_authentication_results` | Нет | Новая доставка с валидным transport evidence |
| Отозван доступ пользователя | Повтор gate на replay **блокируется** | — |

### Доверенные доказательства (не персистить как truth)

- Transport auth — только в момент ingress (fixture/adapter); в карантине хранить **enum snapshot** `transport_trust_level: none|fixture|provider` и **не** boolean из письма.
- `message_digest` — привязка тела к slot, не аутентификация.

### Запрет

Любой переход **карантин → preview** обязан вызывать:

1. `evaluate_mail_admission` (с актуальным transport bundle),
2. проверку источника,
3. существующий `_ingest_message` / receive_import.

Кнопка «принять из карантина» **не** реализуется как skip gate.

---

## 7. API/UI контракт (будущая реализация)

Операции (имена иллюстративные):

| Операция | Право | Успех | Ошибки |
| --- | --- | --- | --- |
| `GET .../companies/{id}/mail-quarantine` | read finance | список open/closed | 403, 404 |
| `GET .../mail-quarantine/{entry_id}` | read finance | метаданные + allowlist headers | 404 |
| `POST .../mail-quarantine/{entry_id}/resolve` | write + paid | `closed` | 403, 402, 409 (already closed) |
| (internal) `record_on_ingress_reject` | service | insert idempotent | — |

**Аудит:** `audit_log` event `mail_quarantine_recorded`, `mail_quarantine_resolved` (user_id, entry_id, resolution).

**UI (будущее):** таб «Почта / Карантин», фильтр по источнику и status; без скачивания вложений в v1.

---

## 8. Миграция и откат

### Порядок (после разрешения)

1. Alembic SQL: таблица + FK composite (как `ingestion_deliveries` scope 0012).
2. RLS enable + policies; negative tests.
3. Функция записи из ingress (feature flag `MAIL_QUARANTINE_ENABLED=false` default).
4. Функция `app_expire_mail_quarantine_entries` + retention job за флагом worker.

### Совместимость

- Backend без флага: ingress без записи карантина (поведение как `c0ca436`).
- Frontend: без изменений до UI-пакета.
- Образ API: additive migration only.

### Downgrade

- Drop policies → drop table; ingress теряет persist reject (acceptable downgrade note).
- Guard: не downgrade если `open` review > 0 без экспорта (как ingestion guard 0011).

### Backup/restore

- Таблица в общем PG backup; JSONB без секретов.
- Restore checkpoint: RLS policies included in migrations.

### Staging

- **Отдельное разрешение владельца:** включение `MAIL_QUARANTINE_ENABLED`, retention job, любой blob store.
- `POLL_IMAP` / `SEND_*` не включаются этим пакетом.

---

## 9. Тестовая матрица (будущая реализация)

| Область | Тесты |
| --- | --- |
| Unit | переходы status, immutability reason_code, digest binding |
| Integration | reject ingress → row, no import batches; idempotent insert; двойной digest → две строки + anomaly |
| RLS | чужой tenant/company → 0 rows; viewer read, no resolve |
| Права | unpaid resolve → 402; resolve → audit_log |
| Retention function | worker без BYPASSRLS: expire очищает только allowlist JSONB; reason_code/slot сохранены; чужой tenant не затронут |
| Retention function | попытка произвольного UPDATE мимо функции → RLS deny |
| Retention function | `p_limit` и SKIP LOCKED — без длинных блокировок |
| Конкурентность | два INSERT same key → one row |
| Side effects | reject/review: counts deliveries/batches/finance unchanged |
| Gate | нет API «approve quarantine» без admission mock |

---

## 10. Решения по вопросам проектирования (2026-10-21)

| Вопрос | Решение | Статус |
| --- | --- | --- |
| TTL reject/review | **90 / 180** календарных дней — defaults конфига без отдельного регламента v1 | Принято в design |
| Уведомление при `review` | **Нет** email/push в v1; очередь только в UI/API (FA-R04.3+) | Принято в design |
| Support read без BYPASSRLS | **Не допускается** в v1; эскалация только внутри tenant с finance read | Принято в design |
| Blob v2 (encrypted MIME) | **Не включать**, пока нет отдельного решения владельца и пакета FA-R04.2 transport | Отложено |
| Первый production transport | **Не выбран**; DDL v1 не зависит; adapter — отдельный scope после карантина code | Отложено |

Реализация таблицы, функций, worker и staging **не** разрешена этим accepted design.

---

## Согласованность с FA-R04.1 / FA-R04.2.1

| Компонент | Карантин |
| --- | --- |
| `evaluate_mail_admission` | Источник `reason_code` для записи; не дублировать policy |
| `ingest_trusted_local_mail` | Точка вызова `record` на REJECTED/REVIEW до `_ingest_message` |
| FA-R02 delivery | Запись карантина **не** создаёт delivery; delivery только на allow path (как сейчас) |
| Legacy IMAP | Не меняется до отдельного подключения adapter + flag |
