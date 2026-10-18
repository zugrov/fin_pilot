# Контракт логической доставки (IngestionDelivery)

Статус: **проект FA-R00.4** + **реализация FA-R02.1** (см. ниже). Не полный envelope API.

`IngestionDelivery` — транспортная сущность (с **R02.1** есть в PostgreSQL/Python).
Связь с as-is: один файл ≈ один `ImportBatch` по `file_hash`; повторная доставка того же
байтового содержимого — новый delivery/part, тот же batch без повторного parse/commit.
почта ≈ `EmailIngestion` + batch после `receive_import`.

## 1. Идентификаторы

| Поле | Кто задаёт | Назначение |
| --- | --- | --- |
| `delivery_id` | сервер (UUID) | постоянный id доставки после приёма |
| `delivery_key` | клиент | idempotency transport; повтор → тот же `delivery_id` |
| `client_package_id` | клиент (опц.) | внешний номер пакета 1С/банка; конфликт содержимого → `content_conflict` |
| `connection_id` | клиент в теле **и** проверка на сервере | привязка к `SourceConnection`; must match auth scope |
| `part_index` / `chunk_index` | клиент | часть внутри доставки / chunk transport |

Tenant и company **не** берутся только из JSON: сервер определяет их из
сессии (UI), machine token (API, будущее) или заранее привязанного
email-route (почта, FA-R04) и проверяет `open_company` / entitlement.

## 2. Канал и доверенная привязка

| Канал | As-is | Целевое (proposed) |
| --- | --- | --- |
| `ui` | cookie + CSRF + `POST …/imports` | то же + создание delivery record |
| `email` | IMAP + sender string | delivery на message; вложения → parts |
| `api` | нет | Bearer scoped token → connection + company |

`source_connection.namespace` остаётся ключом бизнес-идентичности строк
(`SourceIdentity`), не канал.

## 3. Исходный экземпляр и организация

| Поле | Статус |
| --- | --- |
| `source_instance_id` | TBD (D1); стабильный id базы 1С, не connection_id |
| `source_organization_id` | TBD; id организации внутри базы |

До решения D1 поля optional; сервер не выводит firm из них.

## 4. Наборы данных, период, версия схемы

| Envelope `dataset` | `SourceConnection.dataset` | Формат as-is |
| --- | --- | --- |
| `cash` | `cash` | csv, xlsx, clientbank |
| `revenue` | `revenue` | csv |
| `plan` | `plan` | csv (`planned_cash.csv` в документации) |

Расширения (без полной схемы): `budget` → FA-R07; прочие — вне D3.

- `schema_version` конверта: `"1.0-proposed"` (отдельно от `ImportProfile.schema_version`).
- `period_from`, `period_to`: календарные границы **з заявленного** среза (ISO date).
- `timezone`: IANA, например `Europe/Moscow`.
- `generated_at`: момент формирования у отправителя (RFC3339).

## 5. Вложения, части, хеши, контрольные итоги

**Part** (логическая часть доставки):

- `part_index` (1..N в рамках delivery),
- `dataset`, `format` (`csv` | `xlsx` | `clientbank` | `json_records`),
- `content_sha256` (SHA-256 байтов),
- опционально `filename`, `encoding`,
- либо байты (multipart), либо `records[]` при `json_records`.

Один part с уникальным `(connection_id, content_sha256)` → не более одного
`ImportBatch` (как as-is unique index `import_batches_file_uq`).

**control_totals** (claim, не факт сверки):

- `record_count`, опционально суммы по направлениям/dataset,
- сравнивается после parse; mismatch → delivery flag, commit блокируется
  или только manual override (FA-R02.4, TBD владельца).

## 6. Режим snapshot / delta

| mode | Смысл |
| --- | --- |
| `snapshot` | заявлен полный срез за период; незакрытый chunk → delivery incomplete |
| `delta` | изменения; отсутствие строки **не** tombstone без explicit unpost (FA-R02.2) |

As-is поддерживает только file-level revise через `external_id` + `payload_hash`.

## 7. Связь с партиями и результатами

```
IngestionDelivery (1)
  └─ DeliveryPart (0..N)   ← проект; as-is: неявно 1 file или EmailIngestion
       └─ ImportBatch (0..1 на уникальный file_hash+connection)
            └─ RawImportRow (*)
                 └─ commit → SourceIdentity + финансовая сущность
```

**Ответ API (proposed):** `delivery_id`, `transport_status`, `parts[].batch_id`,
`parts[].batch_status`, `quality_flags`, ссылки на preview/commit существующих
маршрутов `/api/v1/imports/{batch_id}/*`.

Проведение финансов **не** дублируется: `POST /imports/{batch_id}/commit` as-is.

## 8. Кардинальности и минимальное изменение данных

### Целевая кардинальность (вариант B)

| Уровень | Кардинальность | Комментарий |
| --- | --- | --- |
| IngestionDelivery | 1 логическая доставка | один transport idempotency scope |
| DeliveryPart | 0..N на delivery | N вложений email, N chunk, или один UI файл |
| ImportBatch | 0..1 на (connection, content_sha256) | as-is unique; каждый distinct bytes → свой batch |
| RawImportRow | 1..* на batch | без изменений |
| SourceIdentity | 0..1 на (company, namespace, external_id) | as-is |

Один delivery с **тремя** CSV одного dataset → **три** part → **три** batch
(если хеши разные). Один и тот же файл дважды → один batch (as-is).

### As-is gap

- UI/API file: delivery **не** материализован; batch создаётся сразу.
- Email: `EmailIngestion` 1:1 вложение; нет общего родителя на письмо с N файлами.

### Минимальное изменение (проект DDL, не утверждено)

1. Таблица `ingestion_deliveries` (поля transport из §1–6).
2. Таблица `ingestion_delivery_parts` **или** JSONB-массив parts на delivery
   (выбор колоночной формы — TBD FA-R02.1; JSONB быстрее старт, хуже запросы).
3. `import_batches.delivery_id` UUID NULL FK → `ingestion_deliveries.id`.
4. `email_ingestions.delivery_id` NULL FK (опционально на первом шаге).

Миграция backfill: существующие batch с `delivery_id NULL` остаются валидными.

### Альтернатива (не рекомендуется)

Расширить только `EmailIngestion` полем `message_delivery_id` без общей таблицы.
**Минус:** API и UI не получают симметричный transport; multi-channel пакет
не представить; FA-R11 дублирует логику.
