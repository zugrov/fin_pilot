# FA-R04 · Защищённый email-канал

## FA-R04.1 · Локальный серверный gate допуска (2026-10-21)

**Статус:** `local_verified` на базе `749ab5a00ef6b97cd7bf135972d8eb6f712eef56`.
**Не** `deployed`, **не** `accepted`, **не** включённый production email-канал.

### Решение владельца

Локальная разработка FA-R04.1 разрешена на существующих форматах и синтетических данных после принятого FA-R02. Клиентские адаптеры и верификация FA-R03 остаются открытыми. Реальная почта, IMAP, отправки и автопроведение не разрешены.

### Что реализовано

Отдельный типизированный gate «можно ли допустить письмо к последующему созданию preview»:

| Исход | Смысл |
| --- | --- |
| `allow_preview` | Пройдены транспорт (fixture), идентичность From, серверная привязка и write-доступ. Контекст (`tenant`, `company`, `connection`, `actor`, `sender`) только при этом исходе. |
| `reject` | Явный отказ с `reason_code`. |
| `review` | Спорная привязка (несколько From или From другого зарегистрированного пользователя при binding на иного actor). |

Gate **не** создаёт `ingestion_deliveries`, `import_batches`, `email_ingestions`, `source_identities`, финансовые записи или outbox.
Gate **не** подключён к legacy `poll_mailboxes` / `ingest_mailbox`.

### Граница доверия

1. **Недоверенное письмо:** `From`, `Reply-To`, `Authentication-Results` и display name.
2. **Серверная привязка:** `TrustedServerBinding` (connection, tenant, company, actor) — задаётся транспортом/ingress, не заголовками.
3. **Транспорт:** `TrustedTransportAuth` — только из явного fixture/адаптера; это **не** реальный SPF/DKIM/DMARC и не DNS-проверка.

Подделка: если в письме есть `spf/dkim/dmarc=pass` в `Authentication-Results`, а fixture транспорта не подтверждает pass → `forged_authentication_results`.

### Reason codes (устойчивые)

| code | Когда |
| --- | --- |
| `ok` | `allow_preview` |
| `transport_evidence_missing` | Нет fixture транспорта |
| `transport_not_authenticated` | Транспорт не аутентифицировал сообщение |
| `transport_auth_failed` | SPF/DKIM/DMARC не pass на границе fixture |
| `forged_authentication_results` | Заголовок письма притворяется pass без транспорта |
| `sender_missing` | Нет однозначного адреса From |
| `ambiguous_sender` | Несколько From → `review` |
| `sender_not_verified_user` | From не совпадает с подтверждённым email actor |
| `routing_ambiguous` | From — другой активный пользователь, binding на иного actor → `review` |
| `routing_binding_conflict` | Источник не совпадает с binding tenant/company |
| `source_not_found` / `source_type_mismatch` | Нет email-источника |
| `user_inactive` | Пользователь не active |
| `email_not_verified` | Email не подтверждён |
| `forbidden` | Нет finance write (viewer и т.п.) |
| `payment_required` | Нет оплаченного write-доступа |
| `not_found` | Membership/пространство при неверном binding |

Нормализация адреса: `strip().lower()` (`normalize_email`), без объединения plus/dot-алиасов.

### Файлы

- `backend/app/domain/mail_admission.py`
- `backend/app/services/mail_admission_service.py`
- `backend/tests/unit/test_mail_admission_policy.py`
- `backend/tests/integration/test_mail_admission.py`

## FA-R04.2.1 · Локальный ingress через gate в FA-R02 (2026-10-21)

**Статус:** `local_verified` на базе `bc2720fcaac47cc52f61de4003f95898b133462b`.
**Не** полный FA-R04.2, **не** deployed/accepted, **не** production email-канал.

### Решение владельца

Локальный пакет разрешён после FA-R02 без accepted FA-R03. Реальная почта, миграции, staging и IMAP/poll не включаются.

### Цепочка

Синтетическое MIME → лимит размера (`import_max_bytes`) → привязка `message_digest` к fixture-транспорту → разбор заголовков → `evaluate_mail_admission` → проверка `enabled/status` источника → разбор вложений → `mail_service._ingest_message` (delivery/parts/`receive_import`/preview).

| Этап | reject/review | preview |
| --- | --- | --- |
| Gate / источник | Структурированный `MailIngressResult`, без `receive_import` | — |
| После allow | — | Delivery + parts + `email_ingestions` preview, без commit_import |

**Лимиты ingress:** размер сырого MIME ≤ `Settings.import_max_bytes`; вложения только как attachment; запрет `..` и абсolute path в имени файла; без архивов, макросов, HTML/JS и сети.

**Reason codes (ingress, дополнительно к gate):** `message_too_large`, `message_empty`, `message_transport_mismatch`, `mime_invalid`, `attachment_missing`, `unsafe_attachment_name`, `source_disabled`, `delivery_conflict`, `admission_context_missing`.

`TrustedIngressBundle` связывает transport, binding, `MailDeliverySlot` (uidvalidity+uid) и SHA-256 тела письма. Хеш не заменяет SPF/DKIM; подмена тела при том же transport → `message_transport_mismatch`.

### Файлы

- `backend/app/domain/mail_ingress.py`
- `backend/app/services/mail_ingress_service.py`
- `backend/tests/unit/test_mail_ingress_policy.py` (domain unit; basename как у FA-R04.1)
- `backend/tests/integration/test_mail_ingress.py`

Legacy `poll_mailboxes` / `ingest_mailbox` не изменялись и не вызываются.

## FA-R04.2.3 · Локальная реализация постоянного карантина (2026-10-21)

**Статус:** `local_verified` на базе `56a68ec822887a7a8226b88d776beb0665cb3c86` + пакет 0015.
**Не** deployed/accepted, **не** staging, **не** реальная почта, **не** HTTP/UI/resolve.

### Поведение

При `mail_quarantine_enabled=true` ingress вызывает `app_record_mail_quarantine` для
исходов **reject/review** до возврата результата; при `false` — как FA-R04.2.1. Сбой записи
→ `AppError` `mail_quarantine_write_failed`, без превращения reject в allow.

### Файлы

- `backend/alembic/versions/20261021_0015_mail_quarantine.py`, `alembic/sql/0015_*`
- `backend/app/domain/mail_quarantine.py`, `services/mail_quarantine_service.py`, `models/mail_quarantine.py`
- правка `mail_ingress_service.py`, `config.py`
- `tests/unit/test_mail_quarantine.py`, `tests/integration/test_mail_quarantine_integration.py`
- `tests/integration/conftest.py` — `HEAD_REVISION=20261021_0015`, TRUNCATE карантина

## FA-R04.3.1 · API просмотра и закрытия карантина (2026-10-21)

**Статус:** `local_verified` на базе `6cd1dd5271456f8bab5e7f9704ac874084e7bb0c`.
**Не** UI, **не** staging, **не** миграции.

### Эндпоинты (session + CSRF + `X-Tenant-Id`)

| Метод | Путь | Назначение |
| --- | --- | --- |
| GET | `/api/v1/companies/{company_id}/mail-quarantine` | Список (`status`, `limit`≤100, `offset`) |
| GET | `/api/v1/companies/{company_id}/mail-quarantine/{entry_id}` | Карточка |
| POST | `/api/v1/companies/{company_id}/mail-quarantine/{entry_id}/close` | `open`→`closed`, Idempotency-Key |

При `mail_quarantine_enabled=false` — **404**. Закрытие: finance write, verified email,
paid write, audit `mail_quarantine_resolved` (без note в audit).

### Файлы

- `backend/app/api/v1/mail_quarantine.py`, `services/mail_quarantine_api_service.py`
- `backend/app/main.py`, `tests/integration/test_mail_quarantine_api.py`
- `tests/unit/test_http_db_dependency_guard.py` (OpenAPI ops **104**)

### Следующий пакет (не этот scope)

UI карантина, Celery retention schedule, staging, реальный транспорт. `POLL_IMAP` и `SEND_*` не менялись.
