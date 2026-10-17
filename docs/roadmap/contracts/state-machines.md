# Машины состояний приёма (проект FA-R00.4)

As-is уже имеет статусы `ImportBatch` и `EmailIngestion.status`.
Ниже — целевое разделение слоёв для варианта B. Переходы в коде **не реализованы**.

## 1. Получение (transport)

Сущность: **IngestionDelivery** (проект).

| Состояние | Смысл |
| --- | --- |
| `received` | заголовок/метаданные приняты |
| `partially_received` | не все chunk/part |
| `transport_complete` | все части байтов на месте |
| `transport_rejected` | auth, лимит, формат конверта |
| `content_conflict` | тот же `client_package_id`, другой aggregate hash |
| `duplicate_transport` | тот же `delivery_key` |

| Из | Событие | В |
| --- | --- | --- |
| — | первый POST | `received` |
| `received` | часть chunk без финала | `partially_received` |
| `partially_received` | последний chunk | `transport_complete` |
| * | повтор delivery_key | `duplicate_transport` (вернуть существующий) |
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

Сущность: **DatasetCoverage** (проект); as-is только `coverage_through` date.

| Состояние | Смысл |
| --- | --- |
| `unknown` | нет данных / не заявлено |
| `claimed` | отправитель или POST coverage заявил |
| `reconciled` | control totals + сверка OK |
| `closed` | период закрыт уполномоченным (роль TBD) |

| Из | Событие | В |
| --- | --- | --- |
| `unknown` | файл без claim | `unknown` (ClientBank max date **не** closed) |
| `unknown` | completeness_claim в envelope | `claimed` |
| `claimed` | ручной POST coverage / сверка | `reconciled` |
| `reconciled` | close action | `closed` |

**Правило видимости:** delivery с `partially_received` или batch
`completed_with_errors` **не** может переводить coverage в `reconciled`/`closed`
автоматически.

**Противоречие control totals:** coverage остаётся `claimed` или `unknown`;
флаг `control_mismatch` на delivery.
