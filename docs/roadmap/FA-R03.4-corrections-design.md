# FA-R03.4 · Коррекции и коллизии источников (design, суженный объём)

**Статус:** **proposed (ожидает владельца)** — суженный объём, **без кода** в репозитории.  
**Утверждение этого документа не разрешает** product-код, миграции, деплой, сервер, данные клиента, флаги, секреты и платежи. **Миграции** — только после **отдельного** одобрения владельца с указанием **цели** и **среды**.  
**Зависимости:** FA-R03.2 accepted; FA-R02.2 (revision, unpost, idempotency); **обязательно** **[FA-R03.3-min](FA-R03.3-provenance-design.md#fa-r033-min)** (fingerprint + lineage).  
**Порядок:** **3.3-min → FA-R03.4 v1 → FA-R03.3** (полный, `reconciliation_run`). Без fingerprint FA-R03.4 не может надёжно детектировать повтор файла/периода.  
**Отложено в пакет «по запросу клиента»:** **сторно**, **валюты** и смежные кейсы (S5/S8 матрицы).

---

## 1. Цель

Выявлять и классифицировать ситуации, когда **один и тот же денежный факт** или **перекрывающиеся периоды** создают риск двойного учёта или ложного «not_found» в сверке, **не** подменяя роли банка и бухгалтерии.

Authoritative для **денежного потока** остаётся **S1 (ClientBank)**; карточка 51 и ОСВ — **контроль и детализация** (FA-R03.2).

---

## 2. Scope v1 (суженный)

| В scope FA-R03.4 v1 | Вне scope v1 (отдельный пакет) |
| --- | --- |
| **Пересечение периодов** — два импорта/файла покрывают overlapping dates; политика «кто выигрывает» | **Сторно / исправления** (S5) |
| **Один платёж в разных файлах** — один fingerprint/content или один `(direction, date, amount, doc#)` в двух S1 | **Мультивалютность** и пересчёт курсов (S8) |
| **Внутренние переводы** — 55.03, 57.03↔51, собственные счета; не смешивать с operating in/out без правила | Полный UX `owner_confirmed` |
| Отчёт статусов: `duplicate_suspect`, `period_overlap`, `internal_transfer` | Авто-изменение ledger |

---

## 3. Что уже закрывает FA-R02 (не дублировать в FA-R03.4)

| Механизм FA-R02 | Что даёт для FA-R03.4 |
| --- | --- |
| **Transport / HTTP idempotency** (`delivery_key`, `Idempotency-Key`) | Повтор **той же** доставки UI/session не создаёт второй batch |
| **`SourceIdentity` + `external_id`** | Повторная проводка того же логического документа → upsert по identity |
| **`source_revision` + `operation` upsert/unpost** | Явная отмена/замена версии источника; unpost → review, не silent delete |
| **Replay import** | Повтор batch с тем же ключом — предсказуемый ответ без двойного commit |
| **`DatasetCoverage.superseded`** | Смена «полноты» периода при новом import — не путать с bank↔card51 run |

**FA-R03.4** добавляет **кросс-файловый** и **кросс-периодный** слой **над** fingerprint (FA-R03.3) и **не** заменяет idempotency транспорта.

---

## 4. Правила v1 (логика, без реализации)

### 4.1 Пересечение периодов

- При регистрации fingerprint S1: если `[period_from, period_to]` пересекается с существующим fingerprint того же `wallet`/счёта 51.
- Действие: флаг `period_overlap`; в отчёте — список batch/run; **не** auto-merge сумм.
- Решение владельца (операционное): какой batch authoritative для cash dashboard — **последний успешный commit** с явным warning в UI (v2).

### 4.2 Один платёж в разных файлах

- Ключ кандидата: `(company, direction, business_date, amount, document_number_normalized)` + optional hash строки ClientBank.
- Если два **разных** `content_sha256` содержат совпадающий ключ → `duplicate_suspect` с ссылками на оба fingerprint и lineage.
- **Не** суммировать оба в оборот; в сверке с S2 — одна пара, вторая — exception.

### 4.3 Внутренние переводы

- Heuristic v1: корр. счета **55.03**, **57.03**, **50.01**, **51**↔**51** (если встретится), ключевые слова в **локальном** CLI уже частично в `fa_r03_check` (депозиты/investing).
- Класс `internal_transfer` — секция **investing** или **technical**, не operating revenue/expense без отдельного правила FA-R06.
- Сверка с S2: пара может быть **matched** с пометкой `internal_transfer` в metrics run (FA-R03.3), без изменения cash category автоматически.

---

## 5. Входы и выходы

| Вход | Выход |
| --- | --- |
| `import_source_fingerprint`, `import_row_lineage` | Таблица/JSON **correction_finding** (описание DDL — в реализации FA-R03.4, не в FA-R03.3) |
| Существующие S1/S2 runs | Дополненный `reconciliation_run.metrics.corrections_count` по классам |
| CLI `fa_r03_check` (опционально) | Режим `--report-corrections` read-only до записи в БД |

---

## 6. Миграции (только описание, v1)

| Объект | Назначение |
| --- | --- |
| `source_correction_finding` | Append-only: kind, severity, fingerprint_ids[], lineage_ids[], period, JSON details без ПII |
| Индексы | `(company_id, kind, created_at)` |

RLS — как у FA-R03.3. Связь с `reconciliation_run` — optional FK `run_id`.

**Объём:** 1 таблица + policies; **~3–4 дня** реализации после FA-R03.3.

---

## 7. Критерии приёмки (черновик)

- [ ] Synthetic: два S1 с одним платежом → один `duplicate_suspect`, оборот не удвоен.
- [ ] Synthetic: overlapping months → `period_overlap` без silent overwrite FA-R02 batch.
- [ ] Internal transfer case (55.03) → классификация в отчёте, operating total не искажён.
- [ ] Сторно/FX кейсы **не** входят — явно `out_of_scope_v1`.

---

## 8. Пакет «по запросу клиента» (вне v1)

| Тема | Условие старта |
| --- | --- |
| **Сторно** (S5) | Образец из 1С + решение: unpost FA-R02 vs новая операция |
| **Валюты** (S8) | Образец мультивалютной выписки + политика Decimal/курс |

До получения образцов — **не** расширять парсеры.

---

## 9. Связанные документы

- [`FA-R03.3-provenance-design.md`](FA-R03.3-provenance-design.md)
- [`FA-R03.1-sample-matrix.md`](FA-R03.1-sample-matrix.md)
- [`STAGE_FA-R02-bootstrap.md`](STAGE_FA-R02-bootstrap.md) § FA-R02.2, R02.4
