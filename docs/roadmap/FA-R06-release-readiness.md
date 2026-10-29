# FA-R06.2-REL0 · инвентаризация релиза на staging

**Режим документа:** READ-ONLY инвентаризация по записям репозитория.  
**Не выполнялось:** SSH, deploy, миграции, смена флагов, изменение workflows и product-кода.  
**База сравнения (repo):** `f1dcd8626e139998e1881c5fe5a72f67a3cfa7e3` (HEAD `main`: product `9819768…` + docs `faa708b` + chore `f1dcd86`).  
**Staging после REL0 (2026-10-27, принято владельцем с оговоркой):** product **`9819768179bba0c09243f5706dd59df10645dbce`**, schema **`20261022_0016`**, образы candidate (api `sha256:7ff7ba916fc…`, frontend `sha256:0867913db57…`).  
**Предыдущий baseline (G2):** backend `be9e47a…` + frontend `1555575…`, schema **`20261019_0014`**.  
**Следующий пакет:** **не начинать** без решения владельца; **B4** и CI E2E classification/polygon — отдельное approval.

Источники: `docs/roadmap/MASTER_PLAN.md`, `docs/roadmap/STATE.json`, `docs/roadmap/FA-R02-release-phase-A.md`, `docs/runbook-staging.md`, `docs/readiness-live.md`, `docs/roadmap/DECISIONS.md`, миграции Alembic, `.github/workflows/*`, Playwright configs.

---

## 1. Staging по записям репозитория и пробелы проверки

### 1.1 Зафиксированное состояние стенда (документы, не live-опрос)

| Слой | Product / source SHA | Schema | Образ / override |
| --- | --- | --- | --- |
| **api, worker, beat** | `be9e47af63310f3d5745eadf67dddb0e8c6c9442` | **`20261019_0014`** | `finpilot-api:release-be9e47a…`; override `/var/tmp/finpilot-release-be9e47a/compose.override.yml`; manifest `sha256:31b6986…` |
| **frontend** | **`15555751…`** (не be9e47a) | — | `finpilot-frontend:release-1555575…`; override `/var/tmp/finpilot-frontend-1555575/compose.frontend.override.yml` |
| **Доступ** | loopback `127.0.0.1:8090`, Compose `finpilot-staging` | | |
| **Backup freeze FA-R02 (pre-migration)** | | **`schema_before=20261017_0010`** в manifest; layout **`database.dump`** + `attachments/` (не checkpoint `db.dump`) | `finpilot-staging-FA-R02-20261020T063211Z.tar.enc`, SHA-256 `7661414a…`; **не** снимок schema **0014**; откат после **0016** — **новый** backup в окне, не только этот файл |

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
| 6 | **План отката** | Restore из **свежего** encrypted backup (**0014+** на момент окна), не полагаться только на `20261020T063211Z` (0010); образ `release-be9e47a`; frontend `release-7ee85e5`; **без** alembic downgrade при данных |
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
| `ops_scripts_repository_policy` | **Нет** для runtime | **Закрыт 2026-10-24** (выбор политики); **окно не назначено** — предусловия §G (commit ops, список CREATE+verify 0014, …) |

**Итог:** `decisions_needed` не блокируют runtime staging при safe flags; **окно REL0** — операционные предусловия §G, не только governance.

---

## 8. Рекомендация: пакет vs части и порядок

### 8.1 Не выпускать «всё HEAD одним переключателем»

Смешивание **0015 (почта)**, **0016 (классификация)**, **frontend classification**, **urgent Telegram** и **session ingest** повышает blast radius и усложняет откат. STATE уже разделяет: **0015+0016** — scope REL0 execute; **B4** — после accept REL0.

### 8.2 Предлагаемая очередность

1. **REL0-PLAN (accept doc)** — этот документ + явный target product SHA (`9819768`), freeze флагов, критерии smoke, backup/restore.
2. **REL0-ARTIFACTS** — `release-candidate-rel0-artifacts` (manual dispatch) для **9819768** + head **0016**; tarball smoke; **без** deploy.
3. **REL0-BACKUP-VERIFY (обязательно до DDL)** — пробное восстановление свежего encrypted backup во **временную** БД на VPS (не `finpilot` staging): decrypt → `pg_restore --list` → restore в `finpilot_rel0_probe` (или аналог) → read-only проверка `alembic_version`, RLS, counts; **DROP** probe DB после OK. Отмена окна, если verify fail.
4. **REL0-IMAGE-DELIVERY (отдельное разрешение)** — доставка образов кандидата на VPS: `scp` tarball(ов) GHA → `sha256sum -c` → `docker load` → локальные теги `release-candidate-9819768…`; **не** перезаписывать `release-be9e47a` / существующие rollback-теги.
5. **REL0-DB** — maintenance window: новый encrypted backup → **0015** → **0016** → health; financial SQL baseline; **MAIL_QUARANTINE_ENABLED=false**, **SESSION_INGEST_ENABLED=false**.
6. **REL0-BACKEND** — recreate api/worker/beat на загруженном образе **9819768**; smoke read-only + регрессия FA-R01.3 metrics на ООО «Топ».
7. **REL0-FRONTEND** — frontend image с **9819768** tree; rollback tags `release-1555575` / `release-7ee85e5` сохранены на диске.
8. **REL0-STAGING-SMOKE** — read-only + ограниченный write-smoke; classification/polygon **не** destructive seed на staging DB.
9. **REL0-E2E-GATE** — локальные 4+7 на кандидате (выполнено в prep); CI job — отдельная задача.
10. **После accept REL0** — B4, quarantine/session ingest, FA-R02 phase B — отдельные решения.

### 8.3 Частичный выпуск (если сжать scope)

- **Минимальный backend-only REL0:** be9e47a → **9819768** + **0016** **без** **0015**, если карантин не нужен на staging — **не рекомендуется**: **0016** зависит от **0015** в chain; пропуск 0015 потребует ветвления миграций (сейчас **линейная** цепочка). Практически: **0015+0016 вместе**, карантин **выключен** флагом.
- **Frontend-only** (как UX-CALENDAR) **без** backend **9819768** — **нельзя** для `/classification` (API и 0016 обязательны).

---

## Связанные записи

- `docs/roadmap/STATE.json` → `fa_r06_2_classification_evidence`, `baseline.migration_*`, `current_task`: **FA-R06-REL0**
- `docs/roadmap/DECISIONS.md` → FA-R06.2-B2/B3b, `finpilot_test` при checkout
- CI @ 9819768: runs `39908727390`, `39908727418` — `docs/roadmap/STATE.json` → `fa_r06_2_classification_evidence`

**Дата инвентаризации:** 2026-10-23.

---

## REL0 · подготовка (2026-10-23, без deploy)

**Product-кандидат (не принятый staging-релиз):** `9819768179bba0c09243f5706dd59df10645dbce` (`9819768`). Docs/chore после него на runtime не влияют.

### F. Решения владельца (2026-10-23)

| Действие | Статус |
| --- | --- |
| `workflow_dispatch` артефактов для `9819768` | **Разрешён** (только сборка; выполнен run `39922595922`) |
| REL0-IMAGE-DELIVERY на VPS | **Запрещено** до окна и отдельного OK |
| REL0-BACKUP-VERIFY на VPS | **В принципе разрешено**; старт **только** после ответа владельца **«команды ок»** на список из §E (+ при необходимости адаптация `ops/check-restore-checkpoint.sh` под backup `20261020T063211Z`) |
| Maintenance window | **Черновик:** **пн 26.10.2026, с 16:00 MSK** (конец **до 18:30**, решает владелец); подтверждение отдельно |

Подробнее: `docs/roadmap/DECISIONS.md` → FA-R06-REL0.

### A. Фактическое состояние staging (SSH read-only, 2026-10-23)

Доступ: alias **`my-vps`** (runbook); **`hostname` = `iufqpatmbm`** (имя VPS в runbook не фиксировалось; alias совпадает с процедурой FA-R02).

| Проверка | Факт |
| --- | --- |
| **Диск `/`** | 38G total, **27G used, 11G avail (71%)** |
| **Inodes `/`** | **13%** IUse |
| **Alembic** | **`20261019_0014`** |
| **Health** | `http://127.0.0.1:8090/health/live` → **200**; `/health/ready` → **200** |
| **api / worker / beat** | `finpilot-api:release-be9e47af63310f3d5745eadf67dddb0e8c6c9442`; container image id **`sha256:31b6986b3102…`** (api) |
| **frontend** | `finpilot-frontend:release-15555751aafffe1743e60107508ea3df6ca93724`; id **`sha256:3330c797afce…`** |
| **Сервисы** | api, worker, beat, frontend, postgres, redis, proxy — **Up** (api/beat/worker ~3d, frontend ~2d) |

**Флаги (api / worker / beat — одинаково):** `SESSION_INGEST_ENABLED=false`, `MAIL_QUARANTINE_ENABLED=<unset>`, `SEND_REAL_EMAIL=false`, `SEND_EXTERNAL_MESSAGES=false`, `SEND_LIVE_PAYMENTS=false`, `POLL_IMAP=false`, `REFUNDS_ENABLED=false`, `BALANCES_IMPORT_ENABLED=true`, `BILLING_MODE=test`, `EMAIL_PROVIDER_MODE=smtp`.

**Бэкапы** (`/var/backups/finpilot`, newest first): `finpilot-staging-FA-R02-20261020T063211Z.tar.enc` (327712 B) + sidecar sha256; pre-balances 20261018; 20261016 archive.

**Docker finpilot images (rollback-relevant):** deployed **release-be9e47a** / **release-1555575**; также **release-7ee85e5**, **recovery-7ee85e5**, **recovery-73319a7**, **release-73319a7**, rollback/pre/staging tags (см. `docker images` на VPS 2026-10-23). **Нет** образа **9819768**.

**`/var/tmp/finpilot-release-be9e47a/`:** `compose.override.yml`, tarball api be9e47a (~90MB), manifest/checksums (FA-R02 A artifact) — **не удалять**.

**Расхождения с docs:** совпадает с runbook/readiness (be9e47a + 1555575, schema 0014). HEAD **9819768** / **0015+0016** / candidate images — **не на стенде**.

### Анализ совместимости (be9e47a ↔ 0015+0016)

1. **Проверка Alembic при старте / ready:** у **be9e47a** `/health/live` и `/health/ready` — только **`SELECT 1`**, без сверки `alembic_version`. Старый backend **не узнает**, что schema ушла на 0016, пока health не упадёт на SQL/ORM-ошибке.
2. **После DDL 0015+0016 без смены образа:** **0015** — новые таблицы карантина (additive); код be9e47a их **не использует**. **0016** — nullable колонки + FK/CHECK на `cash_transactions` (additive); ORM be9e47a **не содержит** этих полей — типичные SELECT/INSERT по старым колонкам **продолжают работать**; лишние таблицы/колонки PostgreSQL не ломают старые запросы. **Риск:** откат **только** образа на be9e47a при schema **0016** без restore — данные в новых колонках/карантине **несовместимы** с downgrade guards; новый код **9819768** **обязателен** для полноценной классification/evidence и quarantine API.
3. **Образы отката на VPS:** ближайшие пары — **api** `release-be9e47a` (31b6986…), **frontend** `release-1555575` или `release-7ee85e5`; recovery **d552…** (api 7ee85e5). Полный список тегов — вывод `docker images` на VPS (2026-10-23).

### C. Локальный E2E-gate (worktree `9819768`, `finpilot_test` пересоздана)

| Набор | Результат |
| --- | --- |
| classification (4) | **4 passed** (~1.0m) |
| polygon (7) | **7 passed** (~1.2m) |

Не заменяет staging smoke.

### B. Workflow артефактов

`.github/workflows/release-candidate-rel0-artifacts.yml` — только **`workflow_dispatch`**, SHA **9819768179…**, api+frontend, offline smoke, **`retention-days: 21`**, actions pinned (checkout **v4.2.2**, upload-artifact **v4.6.0**). Шаг **Capture image IDs:** `api_id="$(docker image inspect "$API_IMAGE_TAG" --format '{{.Id}}')"` (аналогично frontend) → `rel0-release-manifest.txt`. На раннере GHA это **config digest** (`manifest.json` → `Config` в `docker save` tarball), **не** digest записи **`index.json`**. После `docker load` на VPS `docker inspect .Id` часто = **`index.json` → `manifests[0].digest`** (OCI index). **Не** сравнивать VPS `.Id` с `api_image_id` из manifest напрямую — см. критерии IMAGE-DELIVERY §E. В логах run **`39922595922`** отдельного `docker info` (Storage Driver) **нет**. **`release-image-smoke.yml` (be9e47a) не изменять.**

**Прогон 2026-10-23:** workflow run **`39922595922`**, conclusion **success** (~1m31s). Offline smoke: `runtime_imports_ok`, `safe_defaults_ok`, `alembic_head_ok=20261022_0016`. Checkout product head подтверждён: `9819768179bba0c09243f5706dd59df10645dbce`.

**Артефакты локально (вне git):** `/Users/maximzugrov/rel0-artifacts/run-39922595922/` — api tarball **~90.8 MB**, frontend **~19.9 MB**; `shasum -a 256` совпадает с sidecar `*.sha256` (sidecar из GHA содержит runner path — проверять hash файла в каталоге).

Manifest (фрагмент):

| Поле | Значение |
| --- | --- |
| `workflow_run_id` | `39922595922` |
| `product_source_sha` | `9819768179bba0c09243f5706dd59df10645dbce` |
| `api_image_id` | `sha256:f790289e9e155e9349a9be6b9025b55e4caa48ec6b4be3a5009aa47f0fc11758` |
| `frontend_image_id` | `sha256:a9d23bc69e5a3c7f86de499705259e926c366a47edc02aaa6b36a49a6da693d2` |
| `image_id_kind` | `docker_local_image_id` |
| `note` | `api_image_id`/`frontend_image_id` = `inspect .Id` на **хосте сборки** (config); не registry digest |

**Разбор расхождения 2026-10-25 (Mac, без изменений на VPS):** tarball целый; «ложный» СТОП IMAGE-DELIVERY из‑за сравнения `api_image_id` (config) с VPS `.Id` (manifest index).

| Образ | `manifest.json` → Config | VPS `docker inspect .Id` | `index.json` manifests[0].digest |
| --- | --- | --- | --- |
| api | `f790289e…` | `7ff7ba916fc…` | **`7ff7ba916fc…` (совпадает с VPS)** |
| frontend | `a9d23bc6…` | `0867913db57b…` | **`0867913db57b…` (совпадает с VPS)** |

### D. Локальная репетиция: be9e47a на schema 0016

**Метод:** БД **`finpilot_rel0_compat`**; alembic **be9e47a → 0014**, **9819768 → 0016**; `create_app` be9e47a + `TestClient`; payload/URL из `test_cash.py`, `test_import_api.py`, `test_revenue_api.py`, `test_sales_plan_matching.py`. **pytest be9e47a на 0016 не запускался.**

**Прогон 2026-10-23 (доработанный smoke):** регрессий на schema 0016 **не выявлено** (все шаги OK).

| Операция | HTTP | Вывод |
| --- | --- | --- |
| register / verify-email / GET auth/me | 200 | OK |
| POST company, activate slot | 200 | OK |
| POST wallet (`type=bank`, `code=main`) | 200 | OK |
| POST opening-balance | 200 | OK |
| POST manual cash (`/transactions`) | 200 | OK |
| POST manual classify (`version` + `category_id`) | 200 | OK |
| POST classification-rules #1 и #2 | 200 | OK; UNIQUE `(tenant_id, company_id, id)` из **0016** на INSERT **не мешает** |
| POST cash CSV + commit (строка под правило) | 200 | OK; категория на «аренда офиса» |
| POST cash_ok.csv import | 200 | OK |
| POST revenue sale | 200 | OK |
| POST revenue-cash-match | 200 | OK |
| POST planned-cash | 200 | OK |
| GET classification-rules, cashflow, dashboard, /health/ready | 200 | OK |

**Ограничения be9e47a (не баги DDL):** evidence-колонки `classification_rule_id` / `classification_rule_version` код **не заполняет** (scope **9819768**); quarantine API (**0015**) отсутствует.

Скрипт: `/Users/maximzugrov/rel0-artifacts/be9e47a_on_0016_smoke.py` (`uv run python …` из worktree be9e47a).

### E. Подготовленные команды (не выполнялись на VPS)

**Gate:** §F — BACKUP-VERIFY и команды §E/G на VPS **не запускать**, пока владелец не ответит **«команды ok»**.

#### Формат encrypted backup

Два layout после `openssl enc -d …` → `bundle.tar`:

| Layout | Члены | Пример |
| --- | --- | --- |
| **FA-R02 freeze** | `database.dump`, `manifest.txt` (`schema_before=…`), `attachments/…` | `finpilot-staging-FA-R02-20261020T063211Z.tar.enc` — **до** миграции окна (**0010** в manifest) |
| **checkpoint 20261016** | `db.dump`, `files.tar`, `files.sha256`, `manifest.txt` | `ops/check-restore-checkpoint.sh` |

На VPS **нет** encrypted backup с **`schema_before=20261019_0014`**. Свежий backup + verify с `EXPECTED_ALEMBIC=20261019_0014` — **обязательны в начале окна REL0**.

Probe **2026-10-23:** v1 (SHA `013981f3…`) и v2 (SHA `e150e336…`) на freeze `20261020T063211Z` — **`REL0_BACKUP_VERIFY_OK`**, `EXPECTED_ALEMBIC=20261017_0010`; post-check без probe-БД и temp-файлов.

#### Канон ops (политика принята, см. `DECISIONS.md`)

| Файл | SHA-256 (MANIFEST) |
| --- | --- |
| `ops/rel0/rel0-backup-verify.sh` | `e150e336c7c43eff216362907ce595feb858924a7da2a9ae6ab64baefe19efdf` |
| `ops/rel0/rel0-backup-create.sh` | `a81f5cfe857a56cfe138b067b9f9b6e9d7693fdd1523bc1b9cdc5b80e1c4f5ad` |

Mirror: `/Users/maximzugrov/rel0-artifacts/` (копия канона после commit). Исторические `ops/check-restore-checkpoint.sh` / `finish-restore-checkpoint.sh` — **не** REL0-откат (runbook).

Verify: **`PASSFILE`**, **`EXPECTED_ALEMBIC`**, **`BACKUP`**, **`EXPECTED_SHA`** → `REL0_BACKUP_VERIFY_OK`. Create: **`PASSFILE`** → `REL0_BACKUP_CREATE_OK` (checkpoint `db.dump`).

Запуск (только после «команды ok» на **конкретный list_id**):  
`umask 077; bash …/rel0-backup-verify.sh …` / `bash …/rel0-backup-create.sh <PASSFILE>`.

#### REL0-IMAGE-DELIVERY (**запрещено до отдельного OK**)

Manifest run `39922595922`:

- `api_image_id=sha256:f790289e9e155e9349a9be6b9025b55e4caa48ec6b4be3a5009aa47f0fc11758`
- `frontend_image_id=sha256:a9d23bc69e5a3c7f86de499705259e926c366a47edc02aaa6b36a49a6da693d2`

**Mac (источник артефактов run `39922595922`):**

| Файл | Путь |
| --- | --- |
| api tarball | `/Users/maximzugrov/rel0-artifacts/run-39922595922/finpilot-api-release-candidate-9819768179bba0c09243f5706dd59df10645dbce-run-39922595922-linux-amd64/finpilot-api-release-candidate-9819768179bba0c09243f5706dd59df10645dbce-run-39922595922-linux-amd64.tar.gz` |
| api sidecar | `…/api-image.sha256` (первая колонка **`aeefd38c…`**, путь раннера — **не** для `sha256sum -c` на VPS) |
| frontend tarball | `/Users/maximzugrov/rel0-artifacts/run-39922595922/finpilot-frontend-release-candidate-9819768179bba0c09243f5706dd59df10645dbce-run-39922595922-linux-amd64/finpilot-frontend-release-candidate-9819768179bba0c09243f5706dd59df10645dbce-run-39922595922-linux-amd64.tar.gz` |
| frontend sidecar | `…/frontend-image.sha256` (первая колонка **`f1fa03c7…`**) |

**VPS `DEST`:** `/var/tmp/finpilot-rel0-9819768-run-39922595922` (700).

**Проверка tarball:** сравнить **первое поле** sidecar = `sha256sum` файла на VPS = `shasum -a 256` на Mac. **`sha256sum -c` по sidecar не использовать** (путь `/home/runner/work/_temp/…`).

**Критерии приёмки после `docker load` (вместо «VPS `.Id` == `api_image_id`»):**

| | Критерий | IMAGE-DELIVERY 2026-10-25 |
| --- | --- | --- |
| **(a)** | Тройное совпадение sha256 tarball (sidecar GHA, Mac, VPS) | **OK** |
| **(b)** | Label `org.opencontainers.image.revision` == **`9819768179bba0c09243f5706dd59df10645dbce`** | **OK** (api) |
| **(c)** | Config digest (`tar -xzOf … manifest.json` → `Config`) == `api_image_id` / `frontend_image_id` в `rel0-release-manifest.txt`; **`docker inspect .Id` на VPS** == digest **`index.json` → `manifests[0]`** (из tarball) | **OK** (см. таблицу §B) |
| **(d)** | Offline smoke **внутри** образа на VPS (`--network none`, без секретов) | **OK** 2026-10-25 (+ повтор P-3e) |

**Прогон list_id IMAGE-DELIVERY 2026-10-25:** шаги 0–3 OK; **`docker load` выполнен**; шаг 4 по **устаревшему** правилу «`.Id` == rel0 manifest» — ложный СТОП; по **(a–c)** артефакт **принят**. **`DEST` и tar.gz на VPS не удалять** без решения владельца. Override **не** создавались; compose **не** трогали.

Recreate контейнеров **не** выполнять в IMAGE-DELIVERY.

---

## G. Окно: точный runbook

**Окно (черновик):** понедельник **2026-10-26, с 16:00 MSK**; конец **до 18:30 MSK** — **решает владелец**; слот **подтверждается отдельно** перед «команды ok» на **list_id D**.

**Репетиция list C (2026-10-25):** backup `finpilot-staging-REL0-20261025T134330Z.tar.enc`, sha256 `075896125363b414063df442fdd9fecb6a512b68b1241b85dedc2a78930d9599`, verify **0014** OK — **не** заменяет backup **шага D-1** в окне.

**Предусловия:** политика ops **принята**; **commit** `f94be16f690f5cb2681a7f45134b9b2aa0e3df46` (`ops/rel0/` + MANIFEST); **IMAGE-DELIVERY (a–d) OK** (2026-10-25, §E); **list_id P** выполнен (override + скрипты + read-only §G.P); согласованный **list_id D**; passphrase **`/tmp/finpilot-backup-secret.*/passphrase`** (600/700); `COMPOSE`:

```bash
cd /fin_pilot && docker compose \
  --env-file /fin_pilot/.env \
  -f infra/docker-compose.staging.yml \
  -f /var/tmp/finpilot-release-be9e47a/compose.override.yml \
  -p finpilot-staging
```

**Критерии остановки (fail-closed):** любой шаг ≠ ожидание → **СТОП**, полный вывод, **без** ручных правок на VPS (кроме `RECOVERY_CMD` из create — только после ответа владельца); verify fail → **без DDL**; DDL fail → откат (**§G.9**, уровень по решению); deploy fail → откат образов (**§G.9.1**) или restore БД (**§G.9.2**).

#### list_id D — время (оценка, мин)

| Шаг | Операция | Мин | Примечание |
| --- | --- | ---: | --- |
| D-0 | Диск | 1 | read-only |
| D-1 | Backup create `RESTART_AFTER=no` | 5–8 | api/worker/beat **остаются stopped** |
| D-2 | Backup verify (probe) | 1–3 | verify **не** останавливает сервисы |
| D-3 | DDL 0015→0016 | 3–10 | одноразовый контейнер candidate |
| D-4 | Deploy api/worker/beat candidate | 3–5 | сразу после DDL, **без** поднятия be9e47a |
| D-5 | Deploy frontend candidate | 2–3 | |
| D-6 | Smoke (агент) | 5–8 | health, schema, образы, логи, SQL baseline |
| D-7 | Smoke (браузер, владелец) | 10–15 | классификация, без apply |
| D-8 | **Откат** (по решению) | 5–25 | §G.9.1 или §G.9.2 |
| | **Резерв** | **≥ 25** | типично **~35–50 мин** без restore БД |

**Compose `-f` (полные списки):**

| Режим | api / worker / beat | frontend |
| --- | --- | --- |
| **База окна** (create, verify, DDL, откат backend) | `--env-file /fin_pilot/.env` `-f infra/docker-compose.staging.yml` `-f /var/tmp/finpilot-release-be9e47a/compose.override.yml` `-p finpilot-staging` | — |
| **Выпуск candidate** (D-4–D-6) | `-f infra/docker-compose.staging.yml` `-f /var/tmp/finpilot-release-candidate-9819768/compose.override.yml` `-p finpilot-staging` | `-f infra/docker-compose.staging.yml` `-f /var/tmp/finpilot-release-be9e47a/compose.override.yml` `-f /var/tmp/finpilot-frontend-candidate-9819768/compose.frontend.override.yml` `-p finpilot-staging` |
| **Откат образов** (§G.9.1) | `-f infra/docker-compose.staging.yml` `-f /var/tmp/finpilot-release-be9e47a/compose.override.yml` `-p finpilot-staging` | `-f infra/docker-compose.staging.yml` `-f /var/tmp/finpilot-release-be9e47a/compose.override.yml` `-f /var/tmp/finpilot-frontend-1555575/compose.frontend.override.yml` `-p finpilot-staging` |

Override candidate — §G.2 / **list_id P** (не в IMAGE-DELIVERY).

**Read-only факты VPS (2026-10-25):** сеть Compose — **`finpilot-staging_default`**; в `/fin_pilot/.env` есть **`MIGRATION_DATABASE_URL`** (строка без кавычек вокруг значения — `grep '^MIGRATION_DATABASE_URL=["'"'"']'` → exit **1**; значение **не** логировать).

#### list_id P — подготовка к окну (не backup/DDL/deploy)

| Шаг | Действие | Критерий |
| --- | --- | --- |
| **P-1** | Создать override candidate §G.2 (`umask 077`, каталоги **700**, файлы **600**) | diff к be9e47a/1555575 — только `image` + `MAIL_QUARANTINE_ENABLED` |
| **P-2** | `/var/tmp/finpilot-rel0-artifacts/` + scp `ops/rel0/*` с **`f94be16…`**; `sha256sum -c MANIFEST.sha256` | оба скрипта OK |
| **P-3** | read-only: diff override; `docker compose config --quiet` + `config --images` (выпуск backend/frontend, откат); проверка формы `MIGRATION_DATABASE_URL`; offline `import app.main` + `app.jobs.celery_app` | **без** start/stop/load/backup |

**P-3e (предусловие окна, повторять по желанию перед D):**

```bash
docker run --rm -i --network none --pull never -w /app \
  --entrypoint /app/.venv/bin/python \
  finpilot-api:release-candidate-9819768179bba0c09243f5706dd59df10645dbce \
  <<'PY'
import app.main
import app.jobs.celery_app
print("ok")
PY
```

Ожидание: `ok`. Если `app.main` тянет БД на import — **СТОП**, не обходить.

**Прогон P 2026-10-25:** P-1…P-3 OK.

#### Go/no-go за ~15 минут до **D-0**

| # | Проверка |
| --- | --- |
| 1 | CI **green** на product **`9819768179…`**, ops **`f94be16…`**, docs **`ef0e4c7…`** (последние известные HEAD) |
| 2 | Candidate образы на VPS: load + **(a–d)** §E; теги `release-candidate-9819768…` |
| 3 | Override **P-1** на месте; **P-2** скрипты + MANIFEST OK |
| 4 | Passphrase в менеджере; путь guard `/tmp/finpilot-backup-secret.*/passphrase` |
| 5 | **P-3e** `ok`; владелец на связи; слот **16:00–18:30 MSK** подтверждён |

#### list_id D — шаги (не выполнять без «команды ok»)

| Шаг | Действие | Ожидаемый вывод / критерий | Мин | Стоп |
| --- | --- | --- | ---: | --- |
| **D-0** | `df -P /` | `avail_kb` ≥ 5242880 | 1 | LOW_DISK |
| **D-1** | §G.1 `rel0-backup-create.sh` `$PASSFILE` **`no`** | `REL0_BACKUP_CREATE_OK`, `SERVICES_LEFT_STOPPED`, `.enc`+sidecar **600**; зафиксировать `$ENC`, `$EXPECTED_SHA` | 5–8 | fail → trap / **Владелец** |
| **D-2** | `rel0-backup-verify.sh` … `20261019_0014` `$ENC` `$EXPECTED_SHA` | `REL0_BACKUP_VERIFY_OK`, baseline «Топ»; **verify не вызывает compose stop** | 1–3 | **без DDL** |
| **D-3** | DDL §G.3 | `MIGRATION_OK head=20261022_0016` | 3–10 | Alembic error → §G.3.1 |
| **D-4** | §G.2 deploy backend candidate + **health 30×2 s** (§G.4) | api/worker/beat **Up**, **`HEALTH_OK`** до frontend | 3–5 | fail → §G.9.1/9.2 |
| **D-5** | §G.2 deploy frontend candidate | frontend **Up** | 2–3 | fail → §G.9.1 |
| **D-6** | §G.4 smoke агент | health 200, `0016`, логи без traceback, SQL baseline | 5–8 | **СТОП** |
| **D-7** | §G.4 smoke браузер (**Владелец**) | UI классификация, rule id в артефакт | 10–15 | accept / откат |
| **D-8** | §G.9.1 или §G.9.2 | по уровню | 5–25 | только **решение владельца** |

Сеть: `docker network ls | grep finpilot-staging`. Флаги ingest/quarantine/SEND_* **не менять** без решения.

### G.2 Override candidate (создать перед окном, не в IMAGE-DELIVERY)

**Backend** — `/var/tmp/finpilot-release-candidate-9819768/compose.override.yml`:

```yaml
services:
  api:
    image: finpilot-api:release-candidate-9819768179bba0c09243f5706dd59df10645dbce
    environment:
      SESSION_INGEST_ENABLED: "false"
      SEND_REAL_EMAIL: "false"
      SEND_EXTERNAL_MESSAGES: "false"
      SEND_LIVE_PAYMENTS: "false"
      POLL_IMAP: "false"
      REFUNDS_ENABLED: "false"
      BALANCES_IMPORT_ENABLED: "true"
      BILLING_MODE: "test"
      EMAIL_PROVIDER_MODE: "smtp"
      MAIL_QUARANTINE_ENABLED: "false"
    command:
      - /app/.venv/bin/uvicorn
      - app.main:app
      - --host
      - 0.0.0.0
      - --port
      - "8000"

  worker:
    image: finpilot-api:release-candidate-9819768179bba0c09243f5706dd59df10645dbce
    environment:
      SESSION_INGEST_ENABLED: "false"
      SEND_REAL_EMAIL: "false"
      SEND_EXTERNAL_MESSAGES: "false"
      SEND_LIVE_PAYMENTS: "false"
      POLL_IMAP: "false"
      REFUNDS_ENABLED: "false"
      BALANCES_IMPORT_ENABLED: "true"
      BILLING_MODE: "test"
      EMAIL_PROVIDER_MODE: "smtp"
      MAIL_QUARANTINE_ENABLED: "false"
    command:
      - /app/.venv/bin/celery
      - -A
      - app.jobs.celery_app:celery_app
      - worker
      - --loglevel=info

  beat:
    image: finpilot-api:release-candidate-9819768179bba0c09243f5706dd59df10645dbce
    environment:
      SESSION_INGEST_ENABLED: "false"
      SEND_REAL_EMAIL: "false"
      SEND_EXTERNAL_MESSAGES: "false"
      SEND_LIVE_PAYMENTS: "false"
      POLL_IMAP: "false"
      REFUNDS_ENABLED: "false"
      BALANCES_IMPORT_ENABLED: "true"
      BILLING_MODE: "test"
      EMAIL_PROVIDER_MODE: "smtp"
      MAIL_QUARANTINE_ENABLED: "false"
    command:
      - /app/.venv/bin/celery
      - -A
      - app.jobs.celery_app:celery_app
      - beat
      - --loglevel=info
```

**Frontend** — `/var/tmp/finpilot-frontend-candidate-9819768/compose.frontend.override.yml`:

```yaml
services:
  frontend:
    image: finpilot-frontend:release-candidate-9819768179bba0c09243f5706dd59df10645dbce
```

**Diff к `/var/tmp/finpilot-release-be9e47a/compose.override.yml`:** только строки `image:` → тег **candidate**; добавлено **`MAIL_QUARANTINE_ENABLED: "false"`** на api/worker/beat (в be9e47a override ключа нет — default в коде).

**Diff к `/var/tmp/finpilot-frontend-1555575/compose.frontend.override.yml`:** только `image:` → тег **candidate** frontend.

**Read-only на VPS (без секретов):** `cat /var/tmp/finpilot-release-be9e47a/compose.override.yml` и `cat /var/tmp/finpilot-frontend-1555575/compose.frontend.override.yml`.

**D-4 deploy backend:**

```bash
cd /fin_pilot && docker compose \
  --env-file /fin_pilot/.env \
  -f infra/docker-compose.staging.yml \
  -f /var/tmp/finpilot-release-candidate-9819768/compose.override.yml \
  -p finpilot-staging \
  up -d --no-deps --no-build --pull never api worker beat
```

**D-5 deploy frontend:**

```bash
cd /fin_pilot && docker compose \
  --env-file /fin_pilot/.env \
  -f infra/docker-compose.staging.yml \
  -f /var/tmp/finpilot-release-be9e47a/compose.override.yml \
  -f /var/tmp/finpilot-frontend-candidate-9819768/compose.frontend.override.yml \
  -p finpilot-staging \
  up -d --no-deps --no-build --pull never frontend
```

### G.3 DDL 0015→0016 (прецедент FA-R02 phase A на этом VPS)

Maintenance **2026-10-20** (`fa-r02-maintenance-20261020T063211Z.log`): миграция **0010→0014** через одноразовый контейнер **RC-образа**, сеть **`finpilot-staging_default`**, рабочий каталог **`/app`**, команда **`/app/.venv/bin/alembic upgrade head`** (без `-c`; offline smoke GHA `release-candidate-rel0-artifacts` проверяет head через `Config("alembic.ini")` в **`/app`** — тот же путь).

**Для REL0 (list D-3):** образ **`finpilot-api:release-candidate-9819768179bba0c09243f5706dd59df10645dbce`** после IMAGE-DELIVERY **(a–d)**. **Не** монтировать и **не** `source` весь `/fin_pilot/.env` в shell — передать **только** `MIGRATION_DATABASE_URL` (роль миграций, host `postgres` внутри сети):

```bash
NETWORK=finpilot-staging_default
RC_IMAGE=finpilot-api:release-candidate-9819768179bba0c09243f5706dd59df10645dbce
MIGRATION_DATABASE_URL="$(grep '^MIGRATION_DATABASE_URL=' /fin_pilot/.env | cut -d= -f2-)"
POLICY=(
  -e SESSION_INGEST_ENABLED=false
  -e SEND_REAL_EMAIL=false
  -e SEND_EXTERNAL_MESSAGES=false
  -e SEND_LIVE_PAYMENTS=false
  -e POLL_IMAP=false
  -e REFUNDS_ENABLED=false
  -e BALANCES_IMPORT_ENABLED=true
  -e BILLING_MODE=test
  -e EMAIL_PROVIDER_MODE=smtp
  -e MAIL_QUARANTINE_ENABLED=false
)
docker run --rm \
  --network "$NETWORK" \
  -e "MIGRATION_DATABASE_URL=$MIGRATION_DATABASE_URL" \
  "${POLICY[@]}" \
  -w /app \
  "$RC_IMAGE" \
  /app/.venv/bin/alembic upgrade head
docker exec finpilot-staging-postgres-1 psql -U finpilot -d finpilot -At -c "SELECT version_num FROM alembic_version;"
```

**Ожидание:** строки Alembic `Running upgrade … -> 20261021_0015` и `… -> 20261022_0016`; psql → **`20261022_0016`**. **Стоп:** stderr Alembic / revision ≠ 0016 → **§G.3.1** (не сразу restore).

#### G.3.1 Ошибка Alembic (D-3) — дерево решений

1. **Read-only:** `SELECT version_num FROM alembic_version;` (без DDL/deploy).
2. Если **`20261019_0014`** (миграция **не** применилась): поднять api/worker/beat **базовым** override be9e47a (`RECOVERY_CMD` / compose «База окна» **`start`** — **только после «ок» владельца**), **СТОП** окна; **restore БД не нужен**.
3. Если revision **частичная / неожиданная** (не 0014 и не 0016): **СТОП**; **restore БД (§G.9.2)** — **только прямое решение владельца**.
4. Если **`20261022_0016`** при stderr (редко): зафиксировать вывод; решение владельца → D-4 или откат.

#### G.1.1 Отмена окна после D-1 (до DDL)

Если **D-1 fail** или владелец **отменяет** до **D-3**: api/worker/beat могут остаться **stopped** (`RESTART_AFTER=no`). **Не** запускать compose вручную без **«ок»**. Скрипт create при fail печатает **`RECOVERY_CMD=`** (be9e47a override **`start`** api/worker/beat) — выполнять **только** после ответа владельца. Backup `.enc` не удалять.

### G.4 Smoke (D-6 агент / D-7 владелец)

**После D-4 (до D-5):** health-цикл как в create (`RESTART_AFTER=yes`):

```bash
health_ok=0
attempt=0
while [ "$attempt" -lt 30 ]; do
  attempt=$((attempt + 1))
  if curl -sf http://127.0.0.1:8090/health/live >/dev/null \
    && curl -sf http://127.0.0.1:8090/health/ready >/dev/null; then
    health_ok=1
    break
  fi
  sleep 2
done
test "$health_ok" = 1 || { echo HEALTH_NOT_READY; exit 1; }
echo HEALTH_OK
```

**Стоп:** не **HEALTH_OK** → не делать **D-5**; §G.9.

**D-6 — агент (после D-5):**

- `curl -sf http://127.0.0.1:8090/health/live` и `/health/ready` → `{"status":"ok"}`, HTTP 200.
- `alembic_version` = **`20261022_0016`** (psql, как в D-3).
- `docker compose … ps` — api/worker/beat/frontend **Up**; `docker inspect` — теги **candidate**.
- Логи: `docker compose … logs --tail=80 api worker beat` — **нет** traceback; worker содержит **`ready`**.
- SQL baseline ООО «Топ» (read-only, те же числа, что verify **0014**): posted_cash **5**; cash_in **27000.00**; cash_out **46500.50**; opening_active_sum **100000.00**; revenue_oct_ex_vat **20002.00**.

**D-6 — SQL baseline (обязательно `psql -c`, не heredoc):** `docker exec … <<SQL` **не** передаёт stdin в psql → пустой результат и ложный fail. Использовать один вызов `-c` (как D-3) или `docker exec -i … psql` с pipe.

```bash
COMPANY=2f346a28-da63-4ab1-a9e8-611fe7e2dd7d
docker exec finpilot-staging-postgres-1 psql -U finpilot -d finpilot -At -c "
SET row_security = off;
SELECT 'posted_cash=' || count(*)::text FROM cash_transactions
  WHERE company_id = '$COMPANY' AND status = 'posted';
SELECT 'cash_in=' || coalesce(sum(amount) FILTER (WHERE direction = 'in'), 0)::text
  FROM cash_transactions WHERE company_id = '$COMPANY' AND status = 'posted';
SELECT 'cash_out=' || coalesce(sum(amount) FILTER (WHERE direction = 'out'), 0)::text
  FROM cash_transactions WHERE company_id = '$COMPANY' AND status = 'posted';
SELECT 'opening_active_sum=' || coalesce(
  sum(amount) FILTER (WHERE status = 'active'), 0
)::text FROM opening_balances WHERE company_id = '$COMPANY';
SELECT 'revenue_oct_ex_vat=' || coalesce(sum(amount_ex_vat), 0)::text
  FROM revenue_entries
  WHERE company_id = '$COMPANY' AND status = 'posted' AND entry_type = 'sale'
    AND recognition_date >= '2026-10-01' AND recognition_date < '2026-11-01';
"
```

**D-7 — владелец (браузер, SSH-туннель 8090):**

- Вход; фирма **ООО «Топ»**; экран **«Классификация»**.
- Создать **тестовое** правило и повтор с тем же ключом; **preview** — OK; **apply не выполнять**.
- Тестовое правило **отключить** (не удалять); **ID правила** записать в артефакт приёмки окна.

**Стоп D-6:** health / schema / baseline / логи ≠ ожидание → **СТОП**, решение владельца (§G.9).

### G.9 Откат (два уровня — выбор **в момент отказа**)

#### G.9.1 Уровень 1 — только образы (БД **`finpilot` на 0016** не трогаем)

Доказано репетицией **be9e47a @ schema 0016** (§D readiness): backend **0014-кода** на **0016** — read-only smoke OK; health может не ловить schema drift, но **откат приложения без restore БД** допустим, если владелец принимает риск UI/API на старом backend при **0016**.

**Команды (полный `-f`, `--env-file /fin_pilot/.env`, `-p finpilot-staging`):**

```bash
cd /fin_pilot && docker compose \
  --env-file /fin_pilot/.env \
  -f infra/docker-compose.staging.yml \
  -f /var/tmp/finpilot-release-be9e47a/compose.override.yml \
  -p finpilot-staging \
  up -d --no-deps --no-build --pull never api worker beat

cd /fin_pilot && docker compose \
  --env-file /fin_pilot/.env \
  -f infra/docker-compose.staging.yml \
  -f /var/tmp/finpilot-release-be9e47a/compose.override.yml \
  -f /var/tmp/finpilot-frontend-1555575/compose.frontend.override.yml \
  -p finpilot-staging \
  up -d --no-deps --no-build --pull never frontend
```

**Ожидание:** образы **`release-be9e47a`**, frontend **`release-1555575`**; health 200; baseline «Топ» на **0016** (SQL как D-6). **Без** `DROP DATABASE`.

#### G.9.2 Уровень 2 — restore БД из backup **D-1** (schema **0014**)

**Gate:** **`DROP DATABASE finpilot`** и полный restore выполняются **только** при **прямом решении владельца в момент отказа** (отдельная фраза в чате, не «команды ok» на list_id D). До этого решения — только диагностика read-only.

**Источник backup:** encrypted checkpoint **D-1** (`schema_before=20261019_0014`), **не** freeze `20261020T063211Z`.

**Параметры БД (снимок VPS 2026-10-25, read-only):** `ENCODING UTF8`, `LC_COLLATE en_US.utf8`, `LC_CTYPE en_US.utf8`, `datacl` пуст; `pg_db_role_setting` — **0 строк** → после restore **не** требуется `ALTER DATABASE finpilot SET …`, только проверка:

```sql
SELECT datname, pg_encoding_to_char(encoding), datcollate, datctype
  FROM pg_database WHERE datname = 'finpilot';
SELECT setdatabase, setrole, setconfig FROM pg_db_role_setting
  WHERE setdatabase = (SELECT oid FROM pg_database WHERE datname = 'finpilot');
-- ожидание: UTF8, en_US.utf8, en_US.utf8; 0 rows в role_setting
```

**CREATE после DROP** (если владелец подтвердил откат):

```sql
CREATE DATABASE finpilot
  ENCODING 'UTF8'
  LC_COLLATE 'en_US.utf8'
  LC_CTYPE 'en_US.utf8'
  TEMPLATE template0;
```

**Порядок (fail-closed):**

1. **Stop** api, worker, beat (compose «Откат образов», frontend можно оставить или stop — по согласованному list_id).
2. **Decrypt** backup шага 1 → `db.dump`, `files.tar`, `manifest.txt` (временный каталог `/var/tmp/…`, umask 077).
3. **Postgres:** `pg_terminate_backend` для `finpilot` → **`DROP DATABASE finpilot`** → **`CREATE DATABASE`** (параметры выше).
4. **pg_restore** в `finpilot` (list без DATABASE, `--single-transaction`, `--exit-on-error`, `--no-owner`).
5. **Проверка:** `alembic_version` = **`20261019_0014`**; иначе **СТОП**.
6. **Imports** (api/worker/beat **остановлены**; **`IMPORTS_VOL`** — единственный `finpilot-staging_*imports`; **`WORK`** — каталог decrypt backup D-1 с `files.tar`):

```bash
mapfile -t IMPORTS_CANDIDATES < <(docker volume ls -q | grep -E '^finpilot-staging_.*imports$' || true)
test "${#IMPORTS_CANDIDATES[@]}" -eq 1
IMPORTS_VOL="${IMPORTS_CANDIDATES[0]}"
TAR_IMAGE=postgres:16.6-bookworm
docker run --rm --pull never \
  -v "${IMPORTS_VOL}:/imports" \
  "$TAR_IMAGE" \
  sh -c 'find /imports -mindepth 1 -maxdepth 1 -exec rm -rf {} +'
docker run --rm --pull never \
  -v "${IMPORTS_VOL}:/imports" \
  -v "${WORK}:/backup:ro" \
  "$TAR_IMAGE" \
  tar -xf /backup/files.tar -C /imports
```

**Не** `docker volume rm`. **Почему безопасно:** только вложения импорта; `pgdata` / `finpilot` не затрагиваются; содержимое из того же backup, что `db.dump`.
7. **Redis / Celery:** очереди после restore — **только по прямому решению владельца в момент отказа**: либо точечно удалить ключи broker Celery/kombu (префиксы по факту `redis-cli KEYS` на `finpilot-staging-redis-1`, **без** `FLUSHALL` по умолчанию), либо явно зафиксировать отказ от очистки и риск «stale tasks» (worker **не** считать чистым до ручной проверки). **Postgres не трогает.**
8. **Образы:** `up -d --no-deps --no-build --pull never` api/worker/beat + frontend по таблице **«Откат образов»** (`release-be9e47a`, `release-1555575`).
9. **Start** api, worker, beat → health 30×2 s → baseline «Топ» (как verify).

**Критерии СТОП:** decrypt/pg_restore/files/redis/health/baseline ≠ ожидание → **не** продолжать; **владелец**.

**Ожидание успеха:** `RESTORE_FINPILOT_OK` (маркер в list_id), `health/ready` 200, baseline совпадает с probe verify **0014**.

### G.1 REL0-BACKUP-CREATE

**Скрипт:** `ops/rel0/rel0-backup-create.sh` (SHA в MANIFEST). **Runbook:** `docs/runbook-staging.md` § «Копия наполненного staging» — pause/resume api/worker/beat, предусловия. `backend/scripts/backup.py` **не** копирует **`finpilot`**.

**Формат bundle для verify v2:** layout **checkpoint** — члены `db.dump`, `files.tar`, `files.sha256`, `manifest.txt` (v2 `BACKUP_FORMAT=checkpoint`). Альтернатива FA-R02 freeze (`database.dump`) для окна **не** нужна.

**Имя (пример):** `/var/backups/finpilot/finpilot-staging-REL0-<UTC>.tar.enc` + `/var/backups/finpilot/finpilot-staging-REL0-<UTC>.tar.enc.sha256`.

**Что меняется на сервере:** кратковременный stop api/worker/beat; новый файл `.enc` + sidecar; временные каталоги под `/var/tmp` (удалить после успеха). **Откат до DDL:** удалить новый `.enc` если verify не прошёл; сервисы уже подняты — **`finpilot`** не трогали.

**EXPECTED_SHA для v2:** на VPS `sha256sum /var/backups/finpilot/<file>.tar.enc | awk '{print $1}'`; offsite `scp` → Mac `shasum -a 256` — **должен совпасть**; sidecar `sha256sum -c` из каталога backup.

```bash
# Только после «команды ok» владельца на list_id с SHA create из MANIFEST commit.
umask 077
bash /var/tmp/finpilot-rel0-artifacts/rel0-backup-create.sh "$PASSFILE" no
```

**Факты VPS (2026-10-25):** том imports — `finpilot-staging_imports`; tar-образ — `postgres:16.6-bookworm` (local id `sha256:557fea37…`, `tar` в образе есть).

**Verify в окне (шаг 2):**

```bash
umask 077
bash /var/tmp/finpilot-rel0-artifacts/rel0-backup-verify.sh \
  "$PASSFILE" 20261019_0014 "$ENC" <EXPECTED_SHA_ENC>
```

---

## REL0 · приёмка окна (2026-10-27)

**Статус:** **deployed + accepted** владельцем **с оговоркой** (два отключённых smoke-правила — два submit с **разными** `Idempotency-Key`, не дефект продукта).

| Поле | Значение |
| --- | --- |
| Product SHA | `9819768179bba0c09243f5706dd59df10645dbce` |
| Schema | `20261022_0016` |
| Api image | `finpilot-api:release-candidate-9819768…` · `sha256:7ff7ba916fcdb4120632f433477ef5e3dc034f47455afbae95b245fe2743ea1a` |
| Frontend image | `finpilot-frontend:release-candidate-9819768…` · `sha256:0867913db57b9f84a31ccbb07bf9f57c557e7845b15cf16df9094d1ec403e10a` |
| Ops канон | `ops/rel0/` @ `f94be16f690f5cb2681a7f45134b9b2aa0e3df46` |
| Backup D-1 | `finpilot-staging-REL0-20261027T055643Z.tar.enc` · SHA `e9233fa2a5eae93e6fe4fcf68c230158b6500b2f48fc5e31135bc2de161fad70` · verify **OK** (0014 baseline «Топ») |
| D-7 правила (отключены, v2) | `dba429b1-b4b1-4041-8d3f-8df02a31adfd`; `53f7323b-a3f7-46e6-9af3-b716ef2a4418` |
| Apply | не выполнялся (`classification_rule_id` заполненных строк **0**) |
| `mail_quarantine_entries` | **0** |
| Флаги | ingest/quarantine/SEND\_\*/IMAP/refunds **false**; balances import **true**; billing **test** — **без изменений в окне** |

**Post-accept на VPS:** удалён только `/var/tmp/finpilot-rel0-artifacts` (скрипты/MANIFEST); бэкапы, passphrase, override candidate/be9e47a/frontend, образы rollback — **сохранены**.

**Отклонения:** D-6 heredoc (см. §G.4 выше); worker `ready` вне `tail=80`.

**Не проверено:** restore level-2 в `finpilot`; Celery queue policy при откате; classification/polygon E2E в CI.

**Дальше:** B4 и CI — **только решение владельца** (`STATE.json` → `fa_r06_rel0_acceptance`).

---

## REL1 · окно staging 2026-10-28 (закрыто)

**Статус:** **выполнено и закрыто**. Стенд переведён на новый product SHA, схема обновлена, набор правил v1 выключен. Реальные данные клиента на staging **не загружались**.

| Поле | Значение |
| --- | --- |
| Product SHA | `ebd391228a76846f1c805f568467ea8f846e6aa5` |
| HEAD `main` после окна | `d08c35ce01dc159b768d493a6a000494f7d3635b` — **только** allowlist `release-candidate-rel0-artifacts` |
| Schema до → после | `20261022_0016` → **`20261027_0017`** |
| Api/worker/beat image | `finpilot-api:release-candidate-ebd391228a76846f1c805f568467ea8f846e6aa5` |
| Api image `.Id` (VPS, docker inspect) | `sha256:b79d6052e53bb767a15189f5ed1067d3799b12d30926e9733d89dac521dc9f0a` |
| Api tarball sha256 | `68a6c236779a6f68aae069d1ed8a00dd1abd3f8bfbfdcf7a9eb15304d40aea1f` |
| Artifact run | [40651401501](https://github.com/zugrov/fin_pilot/actions/runs/40651401501) · `finpilot-api-release-candidate-ebd3912…-run-40651401501-linux-amd64` |
| Override | `/var/tmp/finpilot-rel0-candidate-ebd3912/compose.override.yml` |
| Frontend | **D-5 пропущен** — на стенде остался `release-candidate-9819768…`; `git diff 9819768..ebd3912 -- frontend/src` **пусто** |
| Backup D-1 | `finpilot-staging-REL0-20261028T081545Z.tar.enc` · SHA-256 `57fe4b435d201f5c370a17ff39b16b5ba570f8f519aa1848e7048674f2cbaa1a` · verify **`REL0_BACKUP_VERIFY_OK`** (`schema_before=20261022_0016`) |
| Offsite | `~/finpilot-backups/` на Mac владельца (вне репозитория), sha256 **совпал**; парольная фраза не копировалась |
| Rollback | образы **9819768** (api+frontend) и **be9e47a** на диске не удалялись |
| Флаги | `CLASSIFICATION_PACKS_ENABLED` **не задавался** (default **false**); `RECEIVABLE_AGING_MAX_ROWS` default **500**; quarantine/SEND\_\*/IMAP/refunds **false**; balances import **true**; billing **test** |

**Smoke D-6 (агент):**

| Проверка | Результат |
| --- | --- |
| `health/live`, `health/ready` | **200 / 200** подряд, логи без traceback |
| Pack routes `preview`/`install`/`disable`/`apply` | **404 ×4** (флаг выключен) |
| Cashflow «Топ» 2026-10-01…31 | поступления **27 000.00**, списания **46 500.50**, `external_count=5`, `net_external=-19 500.50` — совпало с SQL |
| Receivable aging `as_of=2026-10-31` | **200**; итог **8 001.50** = ручная сверка по двум строкам; корзины `0-30 8 001.50`, остальные `0.00`; сумма корзин = итог; структура содержит `completeness`, `quality_flags`, `rows`, `totals_by_bucket`, `rows_truncated`, `unallocated_receipts` |
| ClientBank 2a (cp1251, оба ключа дат, один пуст) | 5 строк `new=5`; повторная загрузка → тот же batch; posted не изменилось; дубликатов `source_identities.external_id` — **0** |
| Сентябрьские операции фикстуры | аннулированы штатным `POST /api/v1/transactions/{id}/void` (5 записей `transaction_void`), **не** SQL; posts «Топ» = **5**, октябрь без изменений |
| Схема после старта | `alembic_version = 20261027_0017`; колонка `linked_sale_entry_id` и индекс `revenue_entries_linked_sale_idx` на месте |

**Отклонения и остаточные риски:**

- **`receivable_demo` на staging не загружался.** ORACLE **47 506,00** и корзины P2 (**32 501 / 5 002 / 5 002 / 5 001**) на стенде **не воспроизводились** — они проверяются на полигоне/CI (`test_receivable_polygon_p2`). Групповой ORACLE **117 500 / 46 000** не пересчитывался.
- Все 5 операций «Топ» остаются в `unmapped`: на стенде нет правил классификации — исходное состояние REL0, не регрессия.
- В `/fin_pilot` на VPS git HEAD `7ee85e5`: деплой шёл образом и override из `/var/tmp`, исходники на сервере не обновлялись.
- Restore **уровня 2** в `finpilot` не репетировался (только probe verify).
- Набор правил v1: `classification_packs_enabled=false`, в tenant **не устанавливался**; hold-out (второй месяц/банк) не проходил → в продукт не включается.
- classification/polygon E2E **не** required checks.

---

## REL1 · окно frontend P4a+P4b (2026-10-29, закрыто и принято)

**Статус:** **закрыто**; P4a и P4b **приняты владельцем 2026-10-29** (приёмка в браузере через SSH-туннель `127.0.0.1:8090`).

| Слой | Значение после окна |
| --- | --- |
| **frontend** | `finpilot-frontend:release-candidate-f1470927045f05c5e35a158baf434006aa0db46b` · `.Id` `sha256:582bd01c8c31…` · контейнер `34d1873ac688` · started `2026-10-29T05:22:05Z` |
| **api / worker / beat** | `finpilot-api:release-candidate-ebd391228a76846f1c805f568467ea8f846e6aa5` — **не перезапускались**: `6a952bda96c7`, `249b61bf9375`, `a2ae6e6bd616`, `StartedAt` `2026-10-28T08:20:49Z` |
| **schema** | **`20261027_0017`** — без изменений |
| **бэкап БД** | не повторялся; используется `.enc` от 2026-10-28 (verify OK, offsite OK) |

| Поле | Значение |
| --- | --- |
| Product SHA | `f1470927045f05c5e35a158baf434006aa0db46b` (P4a `ac06f3e` + P4b `f147092`) |
| Artifact run | [40745480017](https://github.com/zugrov/fin_pilot/actions/runs/40745480017) |
| Artifact name | `finpilot-frontend-release-candidate-f147092…-run-40745480017-linux-amd64` |
| Tarball sha256 | `be2a6b5562878956296883f925b139ba946c268d447561d1e219f2b2dd51abc9` |
| Retention | 21 день (до 2026-11-18) |
| Allowlist | отдельный ci-коммит `abcf0d2`; `ALEMBIC_HEAD` = `20261027_0017` |
| Rollback image | `finpilot-frontend:release-candidate-9819768…` (`sha256:0867913db57b…`) — **оставлен** |

**Смоук:**

| Проверка | Результат |
| --- | --- |
| `health/live`, `health/ready` | **200 / 200** |
| `GET /` | **200**, `text/html`, бандл `index-GG57nPoL.js` (477 004 байта) |
| `GET /assets/*.js`, `*.css` | **200** (`application/javascript`, `text/css`) |
| `GET /cashflow`, `GET /receivables` | **200**, HTML приложения (`<div id="root">`) |
| API cashflow «Топ» октябрь | поступления **27 000,00**, списания **46 500,50**, `external_count=5` |
| API receivable-aging `as_of=2026-10-31` | **8 001,50**, корзина `0-30` = 8 001,50, строк **2** |
| Логи frontend/api/worker/beat | **0 traceback** |

**E2E на продуктивном SHA (ручные dispatch ×2):** [40743997791](https://github.com/zugrov/fin_pilot/actions/runs/40743997791), [40744745826](https://github.com/zugrov/fin_pilot/actions/runs/40744745826) — оба **14 + 4 passed**.

**Ночное расписание (cron) — зафиксированное расхождение:**

- **2026-10-28:** единственный scheduled-прогон [40652211890](https://github.com/zugrov/fin_pilot/actions/runs/40652211890) — success, **7 + 4 passed**, но на коммите **`d08c35c`**, то есть **до P4a/P4b**. Новые экраны он не покрывал: четыре `cashflow-polygon` появились только с P4a.
- **2026-10-29:** scheduled-запусков **0**. Workflow `active`, в самом workflow ошибок нет; GitHub cron — **best-effort** и может пропускаться.
- **Действие:** отдельным ci-коммитом cron изменён с `0 2 * * *` на **`17 3 * * *`**. Больше в workflow **ничего** не добавлено (ни шаг-счётчик, ни required check).

**Откат** (не потребовался): rollback-override на образ `9819768` и `up -d --no-deps --no-build --pull never frontend`; восстановление БД не нужно, данные не менялись.

**Реальные данные клиента на staging не загружались.**
