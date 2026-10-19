# Машины состояний приёма (проект FA-R00.4)

As-is уже имеет статусы `ImportBatch` и `EmailIngestion.status`.
Ниже — целевое разделение слоёв для варианта B.

**FA-R02.1:** transport-статусы `partially_received`, `transport_complete`,
`transport_rejected`, `duplicate_transport` реализованы для UI file и mock-mail;
`content_conflict` / chunk-envelope — вне R02.1.

## 1. Получение (transport)

Сущность: **IngestionDelivery** (проект).

| Состояние | Смысл |
| --- | --- |
| `received` | заголовок/метаданные приняты |
| `partially_received` | не все chunk/part |
| `transport_complete` | все части байтов на месте |
| `transport_rejected` | auth, лимит, формат конверта |
| `content_conflict` | тот же `client_package_id`, другой aggregate hash |
| `duplicate_transport` | повтор transport-ключа (в R02.1 не перезаписывает persisted status) |

| Из | Событие | В |
| --- | --- | --- |
| — | первый POST | `received` |
| `received` | часть chunk без финала | `partially_received` |
| `partially_received` | последний chunk | `transport_complete` |
| * | повтор delivery_key | существующая delivery без смены persisted status |
| * | package_id hash mismatch | `content_conflict` |
| * | 401/403/413/422 envelope | `transport_rejected` |

**Сбой одной части:** delivery остаётся `partially_received`; успешные part
уже имеют batch в preview; delivery **не** `transport_complete`.

**Повтор:** идентичный transport → duplicate; идентичный файл → as-is тот же batch.

## 2. Проверка (parse + preview)

Сущность: **ImportBatch** (as-is + link to delivery).

| Состояние | As-is |
| --- | --- |
| `validating` | да |
| `preview_ready` | да |
| `committing` | да |
| `completed` | да |
| `completed_with_errors` | да (+ `partial_import`) |

| Из | Событие | В |
| --- | --- | --- |
| — | `receive_import` начало | `validating` |
| `validating` | строки разобраны | `preview_ready` |
| `preview_ready` | `commit_import` | `committing` |
| `committing` | успех | `completed` / `completed_with_errors` |
| `preview_ready` | control mismatch | `preview_ready` + delivery `validation_blocked` |

**Конфликт строк:** `duplicate_status=ambiguous` → не commit; delivery не «зелёный».

**Отмена transport:** до commit — void delivery/part flags; batch можно оставить
в preview (audit). После commit — `void_transaction` / будущий unpost (FA-R02.2).

## 3. Проведение (financial)

Сущность: финансовые записи + `SourceIdentity` (as-is).

| Действие | As-is |
| --- | --- |
| create | `proposed_action=create` |
| revise | `changed` + revise_* |
| link | cross-namespace link |
| skip | repeated |
| void | `cash_service.void_transaction` (не через import unpost) |

**Старый revision после нового:** FA-R02.2 — reject or `superseded` row.

**Частичный commit batch:** `completed_with_errors`; delivery **не** считается
полностью проведённым на transport слое (`financial_status=partial` proposed flag).

## 4. Полнота (coverage)

**FA-R02.4 (product be9e47a):** таблица **DatasetCoverage** (`claimed` | `reconciled` | `superseded`) для cash/revenue session ingest + legacy `POST …/sources/{id}/coverage` (claimed only). As-is **`SourceConnection.coverage_through`** сохранён для UI/reports.

| Состояние | Смысл |
| --- | --- |
| `unknown` | нет claim / нет legacy date |
| `claimed` | `completeness_claim` в envelope 1.1 или legacy POST coverage |
| `reconciled` | owner reconcile после matched totals + committed batches |
| `superseded` | invalidation после изменяющего import (connection-wide v1) |
| `closed` | **не реализовано** (будущий пакет) |

| Из | Событие | В |
| --- | --- | --- |
| — | `completeness_claim` (verified datasets) | `claimed` row |
| `claimed` | owner reconcile + gates OK | `reconciled` |
| `reconciled` | import commit same connection | `superseded` (prior reconciled rows) |
| — | legacy POST coverage | `claimed` + `coverage_through` на connection |

**Правило:** auto `reconciled` при matched totals **нет**; partial delta без totals **не** даёт reconciled.

**Delivery validation:** `validation_status` matched/mismatch/not_verifiable/not_checked; snapshot/delta commit gates — см. `session-http-ingest.md`.

**Не реализовано:** period **closed**; multi-chunk snapshot transport; machine coverage.
