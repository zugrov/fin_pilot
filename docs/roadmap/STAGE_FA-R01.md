# FA-R01 · Безопасный сквозной пользовательский путь

Статус этапа: **in_progress** (G0 принят; FA-R01.1 accepted; **FA-R01.2 accepted** на `73319a7`; FA-R01.3 planned).

Зависимость: этап **FA-R00** принят (G0) — контракты и ADR, без обязательной
реализации delivery.

## FA-R01.1 · Явный выбор фirm (малый пакет, подробно)

**Цель.** На записывающих экранах пользователь явно выбирает firm; при нескольких
firm без выбора запись недоступна. Убрать silent `companies[0]` на import, sales,
calendar, alerts, wallets.

**Границы.**

- В scope: UI выбора, сохранение `fp_company_id`, блокировка submit без firm.
- Вне scope: billing, новые API, изменение RLS, Playwright (R01.4), balances.csv (R01.2).

**Затрагиваемые файлы (ожидаемо).**

- `frontend/src/pages/ImportPage.tsx`, `SalesPage.tsx`, `CalendarPage.tsx`,
  `AlertsPage.tsx`, `WalletsPage.tsx`
- `frontend/src/lib/companySelection.ts` (новый, по паттерну Forecast/Budgets/Overview)
- `frontend/src/lib/companySelection.test.ts` (vitest)
- Возможно `frontend/src/pages/OverviewPage.tsx` — унификация helper, без смены поведения

**Backend.** Предварительно не требуется: `company_id` в URL/form уже проверяется
сервером. Diff может показать иное — тогда расширить пакет.

**API / миграции.** Нет.

**Тесты.**

- vitest: helper выбора (preferred, picked, list empty)
- регрессия: `npm test`, `npm run build`
- локально две firm в fixture/seed: файл импорта попадает в выбранную firm
- полный backend pytest без изменений

**Критерии приёмки.**

- При 2+ firm запись без выбора невозможна на перечисленных экранах
- Выбранная firm сохраняется в sessionStorage и подставляется после reload
- Существующие интеграционные тесты backend зелёные без правок финансов

**Риски.**

- Расхождение списка firm между страницами → один helper
- Import multipart form: company только из URL path (не из body) — сохранить

---

## Зависимости остальных задач FA-R01

```text
FA-R00 (G0)
  └─ FA-R01.1 контекст firm
       ├─ FA-R01.2 счета и opening (UI; может трогать wallets API только если нет gap)
       ├─ FA-R01.3 формы, idempotency, связи plan/revenue
       └─ FA-R01.4 приёмка пути (зависит от 1.1–1.3; Playwright)
```

| Задача | Зависит от | Блокирует |
| --- | --- | --- |
| R01.1 | FA-R00 | R01.2–R01.4, FA-R02 UI parity |
| R01.2 | R01.1 | R01.4, пилотные шаблоны opening |
| R01.3 | R01.1 | R01.4, FA-R10 ручные обходы |
| R01.4 | R01.1–R01.3 | FA-R02 (сквозной UX) |

**Порядок реализации:** строго R01.1 → R01.2 → R01.3 → R01.4.

---

## FA-R01.2 · Счета и начальный остаток

Задача **accepted** (принята владельцем **2026-10-18**). Продуктовый SHA **`73319a7dc13a1bae33d0468a2468047afffed891`**. **Пакет 1** остаётся отдельно принятым на **`93428b7`**.

### Пакет 1 · принят (product SHA `93428b758fc581c35b8da933423b11e731a15b90`)

**Приёмка владельцем:** 2026-10-17.

**CI (93428b7):** frontend 83 tests + build; backend 203 pytest PostgreSQL, Ruff, Mypy; run 39038691269.

**Локально:** browser mock wallets-lifecycle A–F (127.0.0.1:8000).

**Staging:** deploy api+frontend finpilot-staging (`127.0.0.1:8090`); read-only smoke Wallets + 7 экранов; write-smoke ООО «Топ»:
create/opening через UI; replay create/opening вернули исходные ID; T-BANK и dashboard (2026-10-01…2026-10-31) без отличий от baseline.

**Приёмочный артефакт на staging (не удалять):** wallet `6337cbaf-5800-4273-8dcd-3c064caaf822` (code `fa-r01-2-smoke-93428b7`); opening `b429046a-7741-40bd-865e-bc2e26e3b22f`; Idempotency-Key create `905d9e37-24bb-4ccf-8821-3d13b8301f66`; opening `f205b4d0-46ff-43b7-bf56-dc8ef2648e25`. Контроль T-BANK `dd1295af-f861-4389-b654-75bdf79aaab0` не изменялся.

Worker/beat на staging при deploy 93428b7 не пересоздавались (образ api c7ff510) — вне доказательств пакета 1.

---

### Пакет 1 · спецификация (историческая)

**Цель (пакет 1).** Безопасное создание счёта и установка active opening из UI; идемпотентность POST
wallet/opening на существующей таблице `idempotency_records`; аддитивное поле `active_opening` в ответе
списка кошельков.

**В scope пакета 1.**

- **Изменение API-контракта (пакет 1):** `POST .../wallets` и `POST .../opening-balance` **требуют**
  заголовок `Idempotency-Key`. Это не обратно совместимо со старыми клиентами без ключа.
  `GET .../wallets` — аддитивно поле `active_opening`.
- Backend: scopes
  `wallet_create`, `wallet_opening`; replay без повторного audit; `duplicate_wallet_code` → 409.
- Frontend: `WalletsPage` — список, создание, opening с подтверждением; TZ фирмы или явный offset;
  сохранение ключа при повторе одного действия.
- Тесты: `test_wallets_idempotency.py`, правки helpers; vitest `walletForm.test.ts`.

**Вне пакета 1 (остаётся в FA-R01.2).**

- история `replaced` в UI, wallet access UI, ImportPage wallet picker (не обязательный объём пакета 2).
- Приёмка всей FA-R01.2 — выполнена после пакета `balances.csv` и smoke (см. пакет 2 ниже).

**Миграции пакета 1.** Нет (IdempotencyRecord уже есть).

---

### Пакет 2 · balances.csv · принят (product SHA `73319a7dc13a1bae33d0468a2468047afffed891`)

**Приёмка владельцем:** 2026-10-18 (вместе с задачей FA-R01.2).

**CI исправленного кода:** run **39119642860** (success, SHA `73319a7…`); release pass run **39126116053** (success); recovery-image run **39126118823** (success).

**Staging:** schema **`20261017_0010`**; deploy api `recovery-73319a7`, frontend `release-73319a7`, override `/var/tmp/finpilot-release-73319a7/compose.override.yml`; runtime **`BALANCES_IMPORT_ENABLED=true`** (override, recreate api only).

**Browser smoke C.7–C.13 (авторизованный, ООО «Топ»):** preview before/after (replace, Europe/Moscow); commit **completed**, `rows_committed=1`; **completed replay** без новой active opening; повтор файла — **тот же batch** (dedup); на smoke wallet **1 active + 1 replaced**; **нет diff** T-BANK / dashboard (cash **80499.50**).

**Приёмочные артефакты (не удалять, не изменять):**

| Роль | ID / значение |
| --- | --- |
| balances-source | `b223b0d5-f149-4556-be7a-9657abed6e6a` («Остатки») |
| import batch | `7d28ba99-24d3-4e71-8182-cae6d4adee52` |
| smoke wallet | `6337cbaf-5800-4273-8dcd-3c064caaf822` (`fa-r01-2-smoke-93428b7`) |
| текущий active opening (после import) | **0.00** на **`2026-10-02T00:00:00+03:00`** (UTC storage `2026-10-01T21:00:00+00:00`) |

**История исправлений пакета 2:** корректирующий коммит `73319a7` — единая `normalize_balances_line` для upload/refresh; preview с `wallet_code`, `currency`, `company_timezone` (CI **39119642860**).

**Статус (историческая спецификация 2026-10-17):** контракт согласован; локальная verification и миграция `20261017_0010` — см. таблицы ниже.

**Цель.** Импорт начальных остатков из `balances.csv` через существующий pipeline `ImportBatch` / preview / commit, с вызовом **`wallet_service.set_opening_balance`** (тот же механизм replaced/active, что Wallets UI). Второй import/opening framework не строить.

**Решения владельца (нормативно).**

| Тема | Решение |
| --- | --- |
| `as_of` | Только `YYYY-MM-DD`; момент = начало дня в `companies.timezone` |
| `balance` | Opening anchor; `0.00` допустим |
| Счета | Только существующие в выбранной firm |
| Дубликаты `wallet_code` в файле | Блокируют commit всего batch |
| Валюта | Строго совпадает с валютой счёта |
| Preview | Без изменения финансов; create / replace / unchanged + до/после |
| Commit | All-or-nothing |
| Completed batch | Replay commit без повторного применения |
| Stale | 409; refresh preview + новое подтверждение |
| Побочные эффекты | Без автоматических alerts / внешних действий |

**Документ контракта:** `docs/import-formats.md` (секция balances.csv; явно «не реализован»).

**Хранение preview / stale (без предположения «миграции нет»).**

- **`raw_import_rows.normalized_payload` (JSONB, уже есть):** `values` (исходные поля), `wallet_id`, `effective_at` (ISO), `intent` (`create` \| `replace` \| `unchanged`), `before` (snapshot active opening: `opening_id`, `amount`, `effective_at` или null), `after` (целевые `amount`, `effective_at`), `stale_guard` (копия `before` на момент preview).
- **`raw_import_rows`:** `validation_errors`, `duplicate_status`, `proposed_action` — как у других datasets; для balances `proposed_action` commit только у valid строк; batch-level duplicate → все строки invalid или batch flag (см. код).
- **`import_batches`:** `file_hash`, `status`, `rows_*`, `quality_flags` — dedup файла и completed replay; опционально **`quality_flags`** вроде `duplicate_wallet_in_file`, `balances_commit_blocked`.
- **Опциональная миграция (если без неё неудобно API):** аддитивный `import_batches.preview_context JSONB` (revision, `prepared_at`, hash снимка opening по wallet_ids) — **не создавать до оценки в коде**; при реализации выбрать row-only vs batch-level guard.

**Commit guard:** перед записью сравнить текущий active opening с `stale_guard`; несовпадение → **409** `stale_preview`. Блокировка кошельков: `SELECT … FOR UPDATE` по wallet_id в **отсортированном** порядке в одной транзакции commit (общая защита от гонок с другим batch и с ручным opening).

**API (ожидаемо, без нового финансового ядра).**

- `create_source`: разрешить `dataset=balances` только вместе с реализацией; до релиза — 422 как сейчас для unknown.
- `POST …/imports` — upload + prepare (как сейчас).
- **`POST …/imports/{batch_id}/refresh-preview`** (новый) — пересчитать prepare по сохранённым `raw_payload`, обновить `normalized_payload` и snapshots; **не** обходить dedup по `file_hash` (тот же batch_id).
- `GET …/preview` — расширить ответ rows: `intent`, `before`, `after` (из normalized, без лишних секретов).
- `POST …/commit` — ветка `dataset==balances`: all-or-nothing, без `completed_with_errors` partial opening.

**Файлы кода (план).**

| Область | Файлы |
| --- | --- |
| Reader | `backend/app/domain/imports/balances_reader.py` (новый) или рядом с plan/revenue readers |
| Prepare/commit | `backend/app/services/balances_import.py` (новый): `prepare_balances`, `commit_balances_row`; интеграция в `import_service.py` |
| TZ / moment | reuse `Company.timezone` + helper (как Wallets UI / `buildOpeningEffectiveAt` на frontend); backend: явная функция start_of_day_in_tz |
| Opening | `wallet_service.set_opening_balance` (+ audit); unchanged — skip write |
| API | `backend/app/api/v1/imports.py` — refresh-preview route |
| Frontend | `ImportPage.tsx`, `api.ts` — dataset `balances`, отображение до/после, обработка 409 stale → refresh |
| Docs | `docs/import-formats.md` — снять пометку «не реализован» только после релиза |
| Fixtures | `backend/tests/fixtures/imports/balances_*.csv` |

**Тест-план (integration + регрессия).**

- Preview не создаёт/не меняет `opening_balances` и audit opening.
- `0.00`; unchanged (active уже совпадает); create; replace.
- Invalid amount / date / currency; unknown `wallet_code`; duplicate `wallet_code` in file → batch blocked.
- Две firm / tenant isolation; права write / replay после revoke (как wallet idempotency).
- Откат всего batch при ошибке на средней строке.
- Concurrent commit **одного** batch (два запроса) — один успех, второй 409/conflict.
- Два batch с пересечением wallet_id — сериализация через lock, без corrupt active.
- Гонка commit import vs ручной `POST opening-balance` — stale 409 на import или корректная сериализация.
- Stale для create / replace / unchanged после смены opening между preview и commit; refresh preview восстанавливает commit без нового file_hash.
- Completed batch replay commit после ручной замены opening — без повторного import-side replace.
- Повтор байтов файла — тот же batch (dedup).
- Timezone firm → точный `effective_at` (Europe/Moscow и минимум один другой TZ в тесте).
- Регрессия: cash / revenue / plan / budget datasets; пакет 1 wallet/opening idempotency.

**Локальная verification (2026-10-17, `finpilot_test@127.0.0.1:5432`).**

| Команда | Результат |
| --- | --- |
| `uv run pytest tests/integration/test_balances_*.py` | **30 passed** |
| `uv run ruff check .` | all passed |
| `uv run mypy app` | Success, 95 files |
| `npm test -- --run` (frontend) | **83 passed** |
| `npm run build` (frontend) | ok |
| `uv run pytest -ra` (backend полный) | **232 passed, 1 failed** — `test_backup_restore` (pg_dump port 5433); **backup/restore локально не подтверждён** |
| Staging | Пакет 2 **не** выложен, миграция **0010 не** применена; `balances.csv` на staging **недоступен** |

Миграция `20261017_0010`: `SET LOCAL lock_timeout/statement_timeout`, `LOCK source_connections`, DROP/ADD CHECK; downgrade — guard `downgrade_blocked` до DROP при строках `dataset=balances`.

**Rollback образа `93428b7`:** при уже существующих `source_connections.dataset=balances` или batch balances **небезопасен** — старый `import_service` направляет upload в cash `_parse` (`ImportFormatError` на balances.csv), ветки `commit_balances_batch` нет. Требуется не откатывать образ без плана по миграции и данным (без DELETE/UPDATE ради CHECK).

### План восстановления (recovery) при инциденте deploy

**Статус:** recovery **gate** в коде (`balances_import_enabled` / `BALANCES_IMPORT_ENABLED`, default `false`); **recovery-образ не собран и не проверен** — не использовать на staging/production до сборки, конфигурации процесса и CI.

Переключение `BALANCES_IMPORT_ENABLED` — **не** runtime toggle: значение читается из конфигурации процесса при старте api (и worker при будущем deploy); смена требует перезапуска/пересоздания контейнера с обновлённым env. Worker/beat для balances jobs **не добавлялись** — расширять deploy на worker/beat автоматически не требуется.

#### Состояние A · до появления balances-данных (источников/batches/opening)

**Отдельное решение владельца:** допустим координированный откат **схемы и/или образа** (не путать с состоянием B).

**Признаки:** `alembic_version = 20261017_0010`; CHECK допускает `balances`; в `source_connections` нет строк `dataset = 'balances'`; нет completed import batches с balances preview/commit.

**Допустимые действия (координированно, с окном обслуживания):**

1. Остановить api/worker/beat (нет новых import/commit).
2. Убедиться guard downgrade: `SELECT count(*) FROM source_connections WHERE dataset = 'balances'` → **0**.
3. Выполнить **штатный** Alembic downgrade `20261017_0010 → 20261014_0009` (SQL guard не сработает).
4. Откатить **образ приложения** на последний принятый SHA **до** пакета 2 (пакет 1 `93428b7` допустим).
5. Поднять сервисы; smoke: wallets/opening пакета 1, cash/revenue import без balances.

**Запрещено:** DELETE/UPDATE строк ради обхода CHECK; force-downgrade при ненулевом count balances sources.

**Проверки:** integration `test_downgrade_without_balances_rows`; после downgrade balances INSERT в CHECK → fail (как до 0010).

#### Состояние B · после появления balances-источников, batches и/или проведённых opening

**Признаки:** строки `source_connections.dataset = 'balances'` и/или `import_batches` + `opening_balances` / audit от balances commit; downgrade guard **заблокирует** DROP CHECK (`downgrade_blocked`).

**Запрещено:** откат образа на **`93428b7`**, Alembic downgrade `0010` «ради старого образа», удаление balances-истории.

**Совместимый проверенный образ (целевой):**

- Код **≥ `4f66fe8`**, схема **`0010`**, данные **без изменений**.
- Конфигурация процесса: **`BALANCES_IMPORT_ENABLED=false`** (default в Settings).
- Gate в `import_service` (локально: `test_balances_feature_gate.py`):
  - **503** `balances_import_disabled` — create balances source, upload, refresh-preview, commit (включая POST replay).
  - **GET** preview/sources/errors — разрешены; ручной opening; cash/revenue/plan/budget — без регрессии.
- **Не** направлять balances upload в cash `_parse`.

**Сборка recovery-образа (не выполнена — не объявлять built/verified):**

**Попытка локальной сборки 2026-10-17 (SHA `ff96bc5`):** **заблокирована** — локальный Docker недоступен. Перенос на VPS и registry push **не** выполнялись.

**GitHub Actions `recovery-image-smoke` (workflow_dispatch):** сборка `linux/amd64` из `git archive ff96bc5`, offline image smoke без БD/registry, artifact `finpilot-api-recovery-ff96bc5-linux-amd64` (7 дней). **Не** HTTP/DB E2E; integration — CI `39056569658`.

**VPS preflight 2026-10-17 (без deploy):** staging `93428b7`, alembic `20261014_0009`, health 8090 OK; artifact SHA `1d31b72c…`, `docker load` → `finpilot-api:recovery-ff96bc5`. **Image ID:** config `05a8e7ae…` vs manifest `00c26a99…` — один OCI-артефакт run `39057488669`.

**Staging deploy 2026-10-18 (ff96bc5, balances=false):** свежий encrypted backup `finpilot-staging-pre-balances-20261018T093953Z.tar.enc` (SHA `d1970ecd…`, 5 вложений, verify без полного restore); offsite Mac; passphrase-файл удалён после копии. Миграция `20261017_0010`; api `recovery-ff96bc5`, frontend `release-ff96bc5`, override `/var/tmp/finpilot-release-ff96bc5/compose.override.yml`; rollback-теги `*-pre-ff96bc5-20261018T094029Z`; worker/beat не пересоздавались (образ `c7ff510`). Read-only smoke OK; gate 503 на create balances source. **Пакет 2 не accepted**; `BALANCES_IMPORT_ENABLED` не включали.

**Корректирующий пакет (73319a7):** refresh balances через единую `normalize_balances_line`; preview wallet_code/currency/timezone. CI `39119642860` success.

**Release pass 73319a7 (2026-10-18):** CI `39126116053`, recovery run `39126118823`, artifact SHA `4787b46a…`; staging api `recovery-73319a7`, frontend `release-73319a7`, override `/var/tmp/finpilot-release-73319a7/`.

**Browser write-smoke C.7–C.13 (2026-10-18):** зафиксировано в приёмке пакета 2 выше; gate **true** в override сохранён после smoke.

**Целевой артеfact (локально, когда Docker доступен):**

- Context: `git archive ff96bc5 -- backend/` (без `.env`, `.venv`, uncommitted).
- `docker build --platform linux/amd64` → tag `finpilot-api:recovery-ff96bc5`, OCI label revision = полный SHA.
- Offline smoke в контейнере (`--rm --network none`): Settings/gate без БД; checksum `config.py`, `import_service.py`, migration SQL.
- **Отдельно от CI:** HTTP/DB integration (253 pytest на run `39056569658`).

**Deploy-путь (не в этом документе):**

1. Образ api от `ff96bc5`+; env `BALANCES_IMPORT_ENABLED=false`; перезапуск процесса для применения.
2. Staging smoke read + wallets (balances write off).
3. Отдельная приёмка compat — **не** замена accepted `93428b7`. Worker/beat для balances не расширять автоматически.

**Критерии приёмки пакета 2.**

- Выполнены: контракт, CI, образ/deploy, schema 0010, gate runtime, smoke C.7–C.13, артефакты source/batch/wallet.
- FA-R01.2 **accepted** на **`73319a7`** — **2026-10-18** (владелец).

**Вне обязательного объёма пакета 2:** UI истории `replaced`, wallet access UI, расширенный wallet picker на ImportPage.
