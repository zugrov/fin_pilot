# Тест-векторы приёма (11 сценариев ADR-001)

Статус: проект FA-R00.4. Файлы примеров: `examples/`.

Легенда проверок:

- **Schema** — валидность JSON против `ingestion-delivery.schema.json`
  (структура, типы, обязательные поля; **не** права, dedup, атомарность).
- **Integration** — будущий тест backend/HTTP после FA-R02.

| # | Сценарий | Вход | Ожидание transport | Ожидание financial | Schema | Integration |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Один файл через кабинет | `delivery-cash-json-records.json`, channel=ui | `transport_complete`, 1 part → 1 batch preview | commit → те же суммы, что as-is CSV | ✓ envelope + cash_record | parity с `test_import_api` |
| 2 | То же событие email и API | Два envelope, один `external_id`, разный channel и sha256 | 2 delivery, 2 batch | второй → `repeated` или `linked`/`review`, **не** double cash | ✓ | `_other_ids` / identity |
| 3 | Письмо N вложений | `delivery-plan-multi-part.json` | 1 delivery, `partially_received` пока chunk 2/2 не принят | каждый batch commit независимо | ✓ | mail fixture multi-attach |
| 4 | Повтор идентичного пакета | Тот же `delivery_key` и те же sha256 | `duplicate_transport`, те же batch id | commit idempotent | ✓ | IdempotencyRecord + file_uq |
| 5 | Тот же package_id, другое содержимое | Один `client_package_id`, разный `content_sha256` | `content_conflict` | финансы без commit | ✓ | 409 integration |
| 6 | Исправление документа | delta + тот же `external_id`, новый payload_hash | новый batch | `changed` → revise_* | ✓ | revise_import tests |
| 7 | Отмена проведения | void API после commit | delivery `financial_status=partial` if mixed | `void_transaction`; import unpost TBD FA-R02.2 | частично | test_cash void |
| 8 | Старая ревизия после новой | commit старого payload после нового | batch preview | reject or row superseded (FA-R02.2) | ✓ records | новый integration |
| 9 | Частичный сбой multi-chunk | chunk 1 OK, chunk 2 422 | `partially_received` | только chunk1 batch commit | ✓ chunk_count=2 | proposed API |
| 10 | Незавершённый snapshot | mode=snapshot, chunk 1/3 | `partially_received`, **не** `reconciled` | commit gated policy TBD | ✓ | FA-R02.4 |
| 11 | Конфlict control totals | envelope totals ≠ parsed rows | `validation_blocked`, batch preview | commit blocked | ✓ control_totals | FA-R02.4 |

## JSON Schema не доказывает

- дедупликацию и `classify_duplicate`;
- RLS, tenant, `open_company`, entitlement;
- атомарность commit и гонки Idempotency-Key;
- соответствие `content_sha256` фактическим байтам multipart.

Это только **Integration** после реализации.

## Негативные контрактные примеры (Schema)

Каталог `examples/negative/`. Каждый файл **должен** отклоняться в `--mode full`.
Причина и путь печатает `validate_contracts.py`.

| Файл | Нарушение |
| --- | --- |
| `neg-missing-delivery-key.json` | нет обязательного поля |
| `neg-wrong-type-delivery-key.json` | неверный тип |
| `neg-bad-channel-enum.json` | неверный enum |
| `neg-bad-amount-pattern.json` | pattern суммы |
| `neg-bad-date-format.json` | format date |
| `neg-bad-connection-uuid.json` | format uuid |
| `neg-bad-generated-at-format.json` | format date-time |
| `neg-bad-schema-version-const.json` | const schema_version |
| `neg-bad-sha256-pattern.json` | pattern sha256 |
| `neg-chunk-index-below-minimum.json` | minimum integer |
| `neg-extra-root-property.json` | additionalProperties |
| `neg-json-records-without-records.json` | allOf then required records |

`fixtures/schema-unresolvable-ref.json` — отдельная тестовая копия схемы с `$ref`
на отсутствующий `$defs`; локальное разрешение должно падать.
