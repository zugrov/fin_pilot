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

### Следующий пакет (не этот scope)

Подключение доверенного транспорта (провайдер, ingress), вызов gate из адаптера, карантин FA-R04.2+, включение на стенде — отдельное решение. `POLL_IMAP` и `SEND_*` не менялись.
