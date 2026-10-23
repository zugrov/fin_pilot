# FA-R06.2-REL0 · инвентаризация релиза на staging

**Режим документа:** READ-ONLY инвентаризация по записям репозитория.  
**Не выполнялось:** SSH, deploy, миграции, смена флагов, изменение workflows и product-кода.  
**База сравнения (repo):** `f1dcd8626e139998e1881c5fe5a72f67a3cfa7e3` (HEAD `main`: product `9819768…` + docs `faa708b` + chore `f1dcd86`).  
**Последний принятый staging backend (G2):** `be9e47af63310f3d5745eadf67dddb0e8c6c9442`, schema **`20261019_0014`**.  
**Staging frontend (отдельный SHA):** `15555751aafffe1743e60107508ea3df6ca93724` (UX-CALENDAR-01).  
**Следующий пакет в STATE:** `FA-R06-REL0`; классификация **заморожена на B3b**; **B4** отложен до принятия REL0.

Источники: `docs/roadmap/MASTER_PLAN.md`, `docs/roadmap/STATE.json`, `docs/roadmap/FA-R02-release-phase-A.md`, `docs/runbook-staging.md`, `docs/readiness-live.md`, `docs/roadmap/DECISIONS.md`, миграции Alembic, `.github/workflows/*`, Playwright configs.

---

## 1. Staging по записям репозитория и пробелы проверки

### 1.1 Зафиксированное состояние стенда (документы, не live-опрос)

| Слой | Product / source SHA | Schema | Образ / override |
| --- | --- | --- | --- |
| **api, worker, beat** | `be9e47af63310f3d5745eadf67dddb0e8c6c9442` | **`20261019_0014`** | `finpilot-api:release-be9e47a…`; override `/var/tmp/finpilot-release-be9e47a/compose.override.yml`; manifest `sha256:31b6986…` |
| **frontend** | **`15555751…`** (не be9e47a) | — | `finpilot-frontend:release-1555575…`; override `/var/tmp/finpilot-frontend-1555575/compose.frontend.override.yml` |
| **Доступ** | loopback `127.0.0.1:8090`, Compose `finpilot-staging` | | |
| **Backup reference (post FA-R02 A)** | | schema в архиве на момент freeze **0010→0014** | `finpilot-staging-FA-R02-20261020T063211Z.tar.enc`, SHA-256 `7661414a…`, offsite Mac — match |

**Safe flags (override api/worker/beat, `readiness-live.md` / FA-R02 phase A):**

| Флаг | Значение на staging |
| --- | --- |
| `SESSION_INGEST_ENABLED` | **false** |
| `SEND_REAL_EMAIL` | **false** |
| `SEND_EXTERNAL_MESSAGES` | **false** |
| `SEND_LIVE_PAYMENTS` | **false** |
| `POLL_IMAP` | **false** |
| `REFUNDS_ENABLED` | **false** |
| `BALANCES_IMPORT_ENABLED` | **true** |
| `BILLING_MODE` | **test** |
| `EMAIL_PROVIDER_MODE` | **smtp** |
| `MAIL_QUARANTINE_ENABLED` | **не задокументировано на override** (в коде HEAD default **false**; без **0015** таблиц карантина на staging **нет**) |

**Финансовый baseline ООО «Топ» (после FA-R02 A, read-only SQL):** 5 posted cash ops; cash total **80499.50**; revenue oct 2026 **20002.00**; acceptance plan **2.00** (due 2026-10-25, expected 2026-10-27). UUID — `STATE.json` → `fa_r01_3_acceptance`.

**Историческая точка 2026-10-16** в `readiness-live.md` (**0449e8d**, schema **0009**) — **не** текущий staging; не смешивать с be9e47a/1555575.

### 1.2 Что на staging **не** отражает HEAD main

- **Backend-код** на **34 коммита** позади HEAD (см. §2): нет экрана/ API классификации с evidence (**0016**), карантина почты (**0015**), cash-flow completeness, срочных digest FA-R09.P3, доработок полигона в CI и т.д.
- **Schema:** на staging **нет** `20261021_0015`, `20261022_0016` (STATE, DECISIONS B3b, runbook).
- **Frontend HEAD** vs **1555575:** нет UI классификации, bundle не соответствует `d40c9c8`…`9819768`.
- **Разнесённые SHA:** backend be9e47a + frontend 1555575 — **не** «один product commit на стенде» (`readiness-live.md`).

### 1.3 Что **ни разу не проверялось на staging** с момента последнего принятого backend-SHA (be9e47a) / UX-CALENDAR (1555575)

| Область | Локально / CI | На staging |
| --- | --- | --- |
| Миграции **0015**, **0016** | pytest, integration | **не применялись** |
| Mail quarantine (ingress hook, API, retention) | integration, flag default false | **нет** |
| Session ingest HTTP | код в be9e47a, flag **false** | **не включали**, write-path не smoke |
| Cash-flow completeness / FA-R06.1 отчёты | polygon tests | **нет** |
| Classification UI + rule evidence | local E2E (4), backend 619 tests @ 9819768 | **нет** (нет backend + 0016 + UI) |
| Synthetic polygon E2E (7) | local `test:e2e:polygon` | **нет** |
| Telegram urgent high/critical (18421ac…) | polygon/unit tests | **нет** (SEND_* false) |
| Write-smoke новых фич | — | **не выполнялись** (UX-CALENDAR — read-only) |
| Recovery на **новом** SHA | workflow только **7ee85e5** | **не обновлялся** |
| Release image smoke для SHA **> be9e47a** | workflow **ALLOWED_SOURCE_SHA = be9e47a**, **ALEMBIC_HEAD = 0014** | **не готов** без нового workflow scope |
| CI/E2E на **f1dcd86** / полный HEAD docs | product CI @ **9819768** (STATE) | chore/docs-only commits **могут** не иметь отдельного CI до push |
| Диск VPS / место под образы | — | **не** в этом документе; в runbook нет свежей проверки под REL0 |
| FA-R02 **фаза B** | — | **не выполнялась** (явно в FA-R02-release-phase-A) |

---

## 2. Коммиты `be9e47a…` → HEAD (`f1dcd86`) по пакетам

**Всего:** 34 коммита (хронология — oldest first).

### FA-R02 · пост-acceptance (staging уже на be9e47a)

| SHA | Сообщение |
| --- | --- |
| `9698a09` | docs: принять FA-R02 и контроль полноты импорта |
| `485bbca` | ci: собрать принятый RC FA-R02 как image artifact |
| `bceb3c6` | docs: зафиксировать staging-выпуск FA-R02 |

### Инфраструктура тестов / полигон (repo)

| SHA | Сообщение |
| --- | --- |
| `bf6cc2b` | test: fix integration database isolation and backup tooling |
| `67ebae0` | test: add reproducible multi-company synthetic polygon |
| `bb81750` | test: fix E731 in backup restore helper |
| `749ab5a` | test: handle both valid concurrent revision orderings |

### UX-CALENDAR-01 (frontend; staging **только** 1555575)

| SHA | Сообщение |
| --- | --- |
| `1555575` | feat: clarify calendar plan creation and rescheduling |
| `06eec3d` | docs: record UX-CALENDAR-01 staging acceptance |

### FA-R04 · почта (gate → карантин → API)

| SHA | Сообщение |
| --- | --- |
| `bc2720f` | feat: add isolated mail admission gate |
| `c0ca436` | feat: route trusted local mail through admission to preview |
| `56a68ec` | docs: accept mail quarantine design |
| `6cd1dd5` | feat: persist rejected and review mail in quarantine |
| `3efa7cf` | feat: add mail quarantine review api |

### FA-R09 · Telegram digest / urgent

| SHA | Сообщение |
| --- | --- |
| `40fd2c7` | test: verify telegram digest on synthetic polygon |
| `ed812cb` | test: make telegram digest polygon checks non-vacuous |
| `18421ac` | feat: send first high-severity digest alerts urgently |
| `e07bb52` | test: tighten urgent digest checks |

### FA-R06.1 · правила учёта / cash-flow

| SHA | Сообщение |
| --- | --- |
| `3523573` | docs: propose management rules v1 |
| `31f3086` | docs: accept management rules v1 with amendments |
| `4740221` | test: verify cash-flow report against polygon oracle |
| `0af7faa` | docs: align cash-flow rules with polygon findings |
| `23f3dcb` | feat: report cash-flow completeness |
| `0e4bf47` | test: verify classification rules on cash-flow polygon |
| `bfc8171` | feat: allow coverage confirmation for cash sources |

### FA-R06.2 · классификация (frozen @ B3b)

| SHA | Сообщение |
| --- | --- |
| `fae96d9` | fix: make classification rule apply deterministic |
| `e41fd9d` | feat: add classification rule update and unclassified operations api |
| `ade0794` | fix: require at least one classification rule condition |
| `d40c9c8` | feat: add classification screen |
| `db58f0f` | fix: keep classification rule create idempotent |
| `447e728` | fix: classification create guardrails and stale preview (**B2**) |
| `9819768` | feat: classification rule evidence and deterministic order (**B3b**) |

### Документация / chore (без product deploy)

| SHA | Сообщение |
| --- | --- |
| `faa708b` | docs: record classification B2 and B3b evidence |
| `f1dcd86` | chore: ignore generated e2e artifacts |

**Product SHA для релизного кандидата:** `9819768179bba0c09243f5706dd59df10645dbce` (B3b; включает B2). Docs-only commits поверх — не меняют runtime.

---

## 3. Миграции staging (`0014`) → repo head (`0016`)

**Цепочка на main:** `20261019_0014` → `20261021_0015` → `20261022_0016`. Промежуточных ревизий между staging и HEAD **нет**.

| Revision | Файл | Суть upgrade | Downgrade |
| --- | --- | --- | --- |
| **0015** | `20261021_0015_mail_quarantine.py` | SQL `0015_mail_quarantine.sql` — таблицы/RLS карантина почты | `0015_mail_quarantine_downgrade.sql`; **guard:** `downgrade_blocked` если есть `mail_quarantine_entries` со `status=open` и `admission_outcome=review` |
| **0016** | `20261022_0016_classification_evidence.py` | SQL `0016_classification_evidence.sql` — `classification_rule_id` / `classification_rule_version` на `cash_transactions`, FK RESTRICT, CHECK, NOT VALID → VALIDATE | `0016_classification_evidence_downgrade.sql`; **guard:** `downgrade_blocked` если любая строка с `classification_rule_id IS NOT NULL` |

**Порядок применения на staging:** строго **0015 → 0016** (зависимость `down_revision`).

**Обратимость в эксплуатации:**

- Runbook FA-R02 A: откат схемы после **0014** — **restore из backup**, не `alembic downgrade` (`docs/runbook-staging.md`, FA-R02-release-phase-A).
- После **0015/0016** downgrade возможен только на **пустых** данных по guard-условиям; после включения карантина или rule-классификации на staging downgrade **заблокирован** — откат образа **be9e47a** без restore **несовместим** с БД на head **0016**.

**Риск для образа отката:**

- Образ **be9e47a** ожидает schema **0014** и не знает про quarantine/evidence columns.
- Rollback images на диске (api `d552…`, worker/beat `c7ff…`) — под **0014**, не под **0016**.
- **Вывод REL0:** перед DDL — новый encrypted backup; план отката = **restore backup + recreate be9e47a (или сохранённый release tag)**, не downgrade chain.

---

## 4. Новые и чувствительные флаги окружения (HEAD, defaults)

Из `backend/app/config.py` и DECISIONS (не включать без отдельного решения):

| Переменная | Default в коде | Риск на staging |
| --- | --- | --- |
| `SESSION_INGEST_ENABLED` | **false** | **true** открывает session HTTP ingest (idempotency scope `session-ingest`); на be9e47a код уже есть, но **никогда не включали** на staging |
| `SESSION_INGEST_MAX_*` | лимиты envelope/body/parts | актуальны только при ingest=true |
| `MAIL_QUARANTINE_ENABLED` | **false** | **true** без **0015** бессмысленно; с **0015** — персистентный карантин, hook в ingress; API 404 при false (DECISIONS FA-R04.3.1) |
| `MAIL_QUARANTINE_*_TTL_DAYS`, `MAIL_QUARANTINE_DAILY_ENTRY_LIMIT` | 90 / 180 / 200 | retention и лимиты при включении карантина |
| `SEND_REAL_EMAIL`, `SEND_EXTERNAL_MESSAGES`, `SEND_LIVE_PAYMENTS` | default **false** в Settings | override staging уже false; **не** ослаблять при REL0 без решения |
| `POLL_IMAP`, `REFUNDS_ENABLED` | false | реальная почта / refunds |
| `BALANCES_IMPORT_ENABLED` | см. Settings / staging **true** | уже на staging; сохранять осознанно |

**Session ingest:** STATE FA-R02.3 — «включение на staging/prod — отдельное решение».  
**Mail quarantine:** FA-R04.2.3 — `local_verified`, **не deployed**; staging не трогали.

---

## 5. Пробелы до выпуска (checklist REL0)

| # | Требование | Статус по repo |
| --- | --- | --- |
| 1 | **Release-image workflow** для целевого SHA | `release-image-smoke.yml`: `ALLOWED_SOURCE_SHA` = **только be9e47a**, `ALEMBIC_HEAD` = **0014**; для `9819768` нужен **отдельный scope** обновления workflow + прогон (не делать в READ-ONLY) |
| 2 | **Recovery-image** для отката приложения | `recovery-image-smoke.yml`: `SOURCE_SHA` = **7ee85e5** (pre-R02); не покрывает be9e47a/9819768 |
| 3 | **CI green на точном product SHA** | Зафиксировано @ **9819768**: CI `39908727390`, E2E `39908727418` (6 tests). HEAD **f1dcd86**: только docs/chore — перепроверить CI после push |
| 4 | **E2E scope** | Default e2e **не** покрывает classification/polygon (§6) |
| 5 | **План миграции 0015+0016** | Maintenance window, backup, fail-closed recreate, financial re-read SQL (как FA-R02 A) |
| 6 | **План отката** | Restore `7661414a…` или **новый** backup post-0016; образ `release-be9e47a`; frontend `release-7ee85e5` или согласованный tag; **без** alembic downgrade при данных |
| 7 | **Проверка диска VPS** | Нет записи в readiness под новые образы + backup; включить в REL0 execute-phase |
| 8 | **Frontend align** | Решить: deploy frontend @ SHA compatible с **9819768** (не только 1555575) |
| 9 | **Staging smoke** | Read-only + ограниченный write-smoke для регрессии ООО «Топ» после backend deploy |
| 10 | **Принятие REL0 владельцем** | STATE: `FA-R06-REL0`, B4 и расширение CI — после accept |

---

## 6. Покрытие CI и E2E

### 6.1 Что запускает GitHub Actions

| Workflow | Trigger | Scope |
| --- | --- | --- |
| `ci.yml` | push/PR | backend pytest (TEST_PG_PORT 5433), ruff, mypy; frontend unit + build |
| `e2e.yml` | push/PR/dispatch | `npm run test:e2e` → **`playwright.config.ts`** |
| `release-image-smoke.yml` | dispatch | только SHA **be9e47a**, head **0014** |
| `recovery-image-smoke.yml` | dispatch | SHA **7ee85e5** |

### 6.2 Исключения в default E2E (`frontend/playwright.config.ts`)

Project **chromium** `testIgnore`:

- `group-e-synthetic-polygon.spec.ts`
- `classification-polygon.spec.ts`
- каталог `polygon/`

**Причина:** изоляция seed/clock и длительность; основной suite — group A–D + auth setup (`tests.e2e.seed` + `run_api`).

### 6.3 Наборы **не** в CI

| Набор | Config | Tests (STATE) | Подготовка | Время (ориентир) |
| --- | --- | --- | --- | --- |
| **Classification polygon** | `playwright.classification.config.ts` | **4** | `tests.e2e.prepare_polygon` → `polygon-meta.json`; `run_api_polygon`; auth `e2e/polygon/auth.setup.ts` | timeout 180s/test; webServer до 240s |
| **Synthetic polygon** | `playwright.polygon.config.ts` | **7** | то же polygon seed + отдельный `outputDir` | аналогично |

Локальные команды: `npm run test:e2e:classification`, `npm run test:e2e:polygon` (`frontend/package.json`).

**Подтверждение:** @ **9819768** default E2E **6 passed**; classification (4) + polygon (7) — **только локально** (STATE `fa_r06_2_classification_evidence.local_e2e_not_in_ci`).

### 6.4 Предложение отдельного пакета (workflows **не** менять в READ-ONLY)

**FA-R06-REL0-E2E** (или подпакет REL0):

1. Документировать в REL0 execute: обязательный локальный/optional CI job прогон polygon + classification перед staging deploy (manual dispatch или будущий workflow — **отдельное approval**).
2. В CI при расширении: второй job с `TEST_PG_PORT`, `prepare_polygon`, увеличенный `timeout-minutes` (≥35), workers=1; не смешивать с default seed (конфликт clock/tenant).
3. Критерий включения в CI: green на **9819768** ×2 локально + один прогон на чистой `finpilot_test` (см. DECISIONS: сброс БД при checkout).

---

## 7. `decisions_needed` из STATE.json

| ID | Блокирует «реальный» пилот? | Блокирует REL0 на синтетическом staging? |
| --- | --- | --- |
| `first_1c_configuration_platform_and_hosting` | **Да** для 1С-канала | **Нет** (файловый/synthetic путь) |
| `real_pilot_isolation_method_before_launch` | **Да** для данных заказчика | **Нет** при сохранении ООО «Топ» synthetic-only |
| `source_precedence_for_target_pnl_and_balance` | **Да** для полного ОПиУ/баланса | **Нет** для текущего D3 + FA-R06.1 cash-flow |
| `period_close_authority` | **Да** для закрытия периода | **Нет** для deploy классификации/0016 |
| `incoming_mail_provider_and_identity_boundary` | **Да** для production mail | **Нет** при `POLL_IMAP=false`, quarantine **false** |
| `ocr_llm_data_processing_boundary` | **Да** для OCR/LLM ingest | **Нет** для REL0 backend scope |
| `ops_scripts_repository_policy` | **Нет** для runtime | **Нет** ( governance untracked `ops/` ) |

**Итог:** ни один пункт **не обязан** блокировать REL0 **deploy синтетического staging** с выключенными ingest/quarantine/SEND_*; блокеры — **операционная готовность** (§5), не decisions_needed.

---

## 8. Рекомендация: пакет vs части и порядок

### 8.1 Не выпускать «всё HEAD одним переключателем»

Смешивание **0015 (почта)**, **0016 (классификация)**, **frontend classification**, **urgent Telegram** и **session ingest** повышает blast radius и усложняет откат. STATE уже разделяет: **0015+0016** — scope REL0 execute; **B4** — после accept REL0.

### 8.2 Предлагаемая очередность

1. **REL0-PLAN (accept doc)** — этот документ + явный target product SHA (`9819768`), freeze флагов, критерии smoke, backup/restore.
2. **REL0-ARTIFACTS** — release-image (и при необходимости recovery) workflow для **9819768** + head **0016**; tarball smoke; **без** deploy.
3. **REL0-DB** — maintenance window: backup → **0015** → **0016** → health; financial SQL baseline; **MAIL_QUARANTINE_ENABLED=false**, **SESSION_INGEST_ENABLED=false**.
4. **REL0-BACKEND** — recreate api/worker/beat на `release-9819768…`; smoke read-only + регрессия FA-R01.3 metrics на ООО «Топ»; **без** write classification на prod data до сценария.
5. **REL0-FRONTEND** — frontend image с SHA ≥ `d40c9c8` (лучше **9819768** tree) + совместимость API; сохранить rollback tag `release-7ee85e5` / `release-1555575`.
6. **REL0-E2E-GATE (optional parallel)** — локальный polygon (7) + classification (4); решение о CI job — отдельный commit/workflow scope.
7. **После accept REL0** — FA-R06.2-B4, включение quarantine/session ingest, FA-R02 phase B — **отдельные** решения.

### 8.3 Частичный выпуск (если сжать scope)

- **Минимальный backend-only REL0:** be9e47a → **9819768** + **0016** **без** **0015**, если карантин не нужен на staging — **не рекомендуется**: **0016** зависит от **0015** в chain; пропуск 0015 потребует ветвления миграций (сейчас **линейная** цепочка). Практически: **0015+0016 вместе**, карантин **выключен** флагом.
- **Frontend-only** (как UX-CALENDAR) **без** backend **9819768** — **нельзя** для `/classification` (API и 0016 обязательны).

---

## Связанные записи

- `docs/roadmap/STATE.json` → `fa_r06_2_classification_evidence`, `baseline.migration_*`, `current_task`: **FA-R06-REL0**
- `docs/roadmap/DECISIONS.md` → FA-R06.2-B2/B3b, `finpilot_test` при checkout
- CI @ 9819768: runs `39908727390`, `39908727418` — `docs/roadmap/STATE.json` → `fa_r06_2_classification_evidence`

**Дата инвентаризации:** 2026-10-23.
