# Session User Transport API (FA-R02.3)

**Статус:** реализовано в коде; **не accepted**; **не включено** на staging/prod (`session_ingest_enabled=false` по умолчанию).

Это **пользовательский** transport API (cookie + CSRF), **не** machine/1С интеграция. Bearer и `channel=api` — **FA-R11**; целевой контракт остаётся в `ingestion-proposed.openapi.yaml`.

## Маршруты

| Method | Path | Auth |
| --- | --- | --- |
| POST | `/api/v1/companies/{company_id}/ingestions` | session + CSRF + entitlement + write |
| GET | `/api/v1/companies/{company_id}/ingestions` — **нет** | |
| GET | `/api/v1/ingestions/{delivery_id}` | session + read (company из delivery) |

При `session_ingest_enabled=false` → **404**. Заголовок `Authorization: Bearer …` → **401** (даже с cookie).

## Multipart

- Поле `envelope` — JSON (≤ 64 KiB), **ровно одно**; повторное поле `envelope` → **422**.
- Поля `files` — бинарные части **в том же порядке**, что `parts[]` в envelope после сортировки по `part_index` (1..N).
- Не более **8** файлов; **raw** multipart body ≤ **32 MiB** (с boundary/overhead, считается при чтении stream); per-file/row/XLSX — существующие `import_max_*`.
- Concurrent same `delivery_key`: `pg_advisory_xact_lock` на `(user, key)`; replay **200** с сохранённым POST body; idempotency scope `session-ingest`.
- Parse multipart — **async** на event loop; синхронные DB/service фазы (`auth`, `accept_session_ingestion`) — через `run_in_threadpool` (одна `DbSession` на запрос, без параллельного использования).
- После parse (успех или ошибка валидации полей) все `UploadFile` из form закрываются явно; при ошибке parse parser закрывает временные file handles из `_files_to_close_on_error`.

## Envelope (`schema_version = "1.0-session"`)

Разрешены **только** поля:

- `schema_version`, `delivery_key`, `connection_id`, `channel` (`"ui"`), `parts[]`
- part: `part_index`, `dataset`, `format`, `content_sha256`

Любые другие поля (`client_package_id`, `mode`, period, `control_totals`, `json_records`, …) → **422**.

`Idempotency-Key` **обязан** совпадать с `delivery_key`. Scope idempotency: `session-ingest` (отдельно от `import-upload`).

Transport key (внутренний): `session-ingest:{user_id}:{delivery_key}`.

Fingerprint: version `1`, channel `ui`, company, connection, manifest `part_index:dataset:format:sha256`.

## Semantics

- Bytes → `receive_import` (один pipeline); **без** auto `commit_import`.
- Ожидаемая ошибка части (413/422, коды validation/unsupported/payload_too_large) → part `failed`, остальные части продолжаются.
- `partially_received` / `transport_rejected` / `transport_complete` — как R02.1 transport.
- Replay: **200** + сохранённое тело POST; первый успех: **201**.
- GET строит актуальный статус из БД; ссылки на batch: `/api/v1/imports/{batch_id}/preview` и `/errors`.

## Settings

- `session_ingest_enabled` (default `false`)
- `session_ingest_max_envelope_bytes` (65536)
- `session_ingest_max_body_bytes` (33554432)
- `session_ingest_max_parts` (8)
