# FA-R06-REL1 · дизайн: classification + polygon E2E в CI

**Режим:** подготовка после приёмки REL0. **Не реализовано:** нет изменений в workflows, коде, VPS.

**Контекст:** default job `e2e` (`.github/workflows/e2e.yml`) запускает `npm run test:e2e` → `playwright.config.ts`, который **исключает** `classification-polygon.spec.ts`, `group-e-synthetic-polygon.spec.ts` и каталог `polygon/` (`testIgnore`). Локально:

| NPM script | Config | `playwright test --list` (2026-10-27, `frontend/`) | Setup-проект |
| --- | --- | --- | --- |
| `test:e2e:classification` | `playwright.classification.config.ts` | **4** tests (1 setup + **3** в `classification-polygon.spec.ts`) | **да:** `[classification-setup]` → `polygon/auth.setup.ts` |
| `test:e2e:polygon` | `playwright.polygon.config.ts` | **7** tests (1 setup + **6** в `group-e-synthetic-polygon.spec.ts`) | **да:** `[polygon-setup]` → тот же `auth.setup.ts` |

**Согласование с STATE:** `fa_r06_2_classification_evidence.local_e2e_not_in_ci` — `classification_tests: 4`, `polygon_tests: 7` — это **полный** вывод `playwright test --list` (**setup-проекты входят** в счёт). Отдельно: **3+6 = 9** spec-тестов без setup; при двух npm script подряд setup выполняется **дважды**.

Проверка (повторять перед правками документа):

```bash
cd frontend && npm run test:e2e:classification -- --list
cd frontend && npm run test:e2e:polygon -- --list
```

---

## 1. Что нужно на `ubuntu-latest`

### 1.1 PostgreSQL

| Параметр | Default E2E (сегодня) | Polygon / classification |
| --- | --- | --- |
| Образ | `postgres:16.6` (service) | **тот же** |
| Порт на runner | `5433→5432` (`TEST_PG_PORT=5433`) | **тот же** |
| БД | `finpilot_test` (создаётся bootstrap) | **то же имя**, но **отдельный lifecycle** job |
| Роль миграций | шаг «Роль для миграций» (SUPERUSER runner) | **идентично** `e2e.yml` |

Polygon **не** использует `tests.e2e.seed` / `run_api` (clock `E2E_FROZEN_ISO`). Использует:

1. `uv run python -m tests.e2e.prepare_polygon` — `ensure_finpilot_test_database` → migrate → `truncate_all` → seed 3 профиля (`ALL_PROFILES`), billing, импорты, `polygon-meta.json`.
2. `uv run python -m tests.e2e.run_api_polygon` — Uvicorn `:8000`, `FixedClock(polygon_frozen_moment())`, `FakeYooKassa`.

Frontend: `npm run dev` `:5173` (как default E2E).

### 1.2 Auth setup

- `frontend/e2e/polygon/auth.setup.ts` → `e2e/.auth/polygon-user.json` (не `user.json` основного suite).
- Owner: `polygon-e2e@example.com` (`prepare_polygon.py`).

### 1.3 Playwright

| Параметр | Default | Polygon configs |
| --- | --- | --- |
| `workers` | 1 | 1 |
| `fullyParallel` | false | false |
| `timeout` (test) | 120_000 ms | **180_000 ms** |
| `expect.timeout` | 20_000 ms | **30_000 ms** |
| `webServer` timeout (API) | 180_000 ms | **240_000 ms** |
| Browser clock | нет (основной seed) | `context.clock.install(POLYGON_CLOCK_ISO)` в spec |

### 1.4 Изоляция от основного E2E

| Риск | Митигация в CI |
| --- | --- |
| Общее имя `finpilot_test` | **Отдельный job** (свой service Postgres) — БД пустая на старте job; конфликта с job `playwright` **нет**. |
| Параллельный запуск polygon + default на одном runner | **Запрещено** (порты 8000/5173). Jobs только **последовательно** или **matrix parallel** на разных runners. |
| Два подряд `prepare_polygon` (classification + polygon configs) | Каждый `playwright test -c …` поднимает **свой** webServer → **двойной** prepare (~1–3 мин). Для CI предпочтительно **один** job: `prepare_polygon` один раз, затем оба config **или** объединённый `playwright.rel1.config.ts` (будущая реализация). |
| `waitForTimeout` / race preview (classification) | Flaky-зона; retries=0 сегодня — при CI рассмотреть **retries: 1 только на CI** для polygon suite (отдельное решение). |
| Скриншоты в `e2e/report-artifacts/` | Не ломают assert; артефакт диска runner — OK. |

### 1.5 Зависимости job (как `e2e.yml`)

- `actions/checkout@v4`, `astral-sh/setup-uv@v5` (Python 3.12), `setup-node@v4` (Node 24).
- `uv sync --group dev --frozen` (backend), `npm ci` (frontend).
- `npx playwright install --with-deps chromium`.
- Env: `TEST_PG_PORT=5433`, `CI=true`.

---

## 2. Оценка времени и лимиты

| Этап | Оценка (чистый runner) |
| --- | --- |
| Install deps + Chromium | ~2–3 min (кэш npm/uv) |
| `prepare_polygon` (1×) | ~1–2.5 min (миграции head **0016**, 3 компании, импорты) |
| Polygon **7** tests (list; 6 spec) | ~3–6 min |
| Classification **4** tests (list; 3 spec) | ~2–5 min (apply + preview race + screenshots) |
| **Итого один job (оба suite, 1× prepare)** | **~8–15 min** |
| **Итого два npm script подряд (2× prepare)** | **~12–20 min** |

Текущий default E2E на main: **~2 min 23 s** (run 40461992994 @ docs-only commit). Backend CI **~8–9 min**.

**Лимит GitHub:** job timeout default 360 min; `e2e.yml` задаёт **25 min** — для polygon suite **недостаточно**, если гонять 2× prepare + **11** tests (4+7 по `--list`). Рекомендуем **`timeout-minutes: 35–45`** для REL1 job.

**Стабильность (flaky):**

- Зависимость от **frozen clock** (UI + API) — стабильна, если не смешивать с default seed.
- Classification test «устаревший preview» — **timing-sensitive** (`waitForTimeout(2500)`).
- Plan move (group-e) — PATCH counting; умеренный риск при медленном CI.
- **Не проверено:** 10+ прогонов подряд на GHA (критерий включения ниже).

---

## 3. Варианты включения в CI

### (A) Отдельный job в `e2e.yml` на каждый `push` / `pull_request`

```yaml
# Фрагмент-предложение (НЕ ПРИМЕНЯТЬ)
jobs:
  playwright:
    # … существующий default 6 tests …
  playwright-polygon-rel1:
    needs: []  # параллельно с playwright, не с backend
    runs-on: ubuntu-latest
    timeout-minutes: 40
    services:
      postgres: { … как в e2e.yml … }
    steps:
      # … deps, chromium …
      - name: Polygon + classification E2E
        working-directory: frontend
        run: |
          npm run test:e2e:polygon
          npm run test:e2e:classification
        env:
          TEST_PG_PORT: "5433"
          CI: "true"
```

| + | − |
| --- | --- |
| Каждый push ловит регресс UI классификации/полигона | **+10–20 min** wall-clock (parallel job) или очередь runners |
| Единый workflow с default E2E | 2× `prepare_polygon` без доработки config |
| Прозрачный required check | Flaky timing → красный main без связи с deploy |

### (B) Отдельный workflow `e2e-polygon.yml`: `workflow_dispatch` + `schedule` (nightly)

```yaml
# Фрагмент-предложение (НЕ ПРИМЕНЯТЬ)
on:
  workflow_dispatch:
  schedule:
    - cron: "0 2 * * *"  # 05:00 MSK
jobs:
  polygon-rel1:
    …
```

| + | − |
| --- | --- |
| Не блокирует каждый push | Регрессия до **24 h** |
| Можно гонять на `main` nightly + вручную перед staging | Нужна дисциплина: смотреть nightly |
| Проще поднять timeout, retries | PR не защищён check'ом без branch rule |

### (C) Только `workflow_dispatch` / тег `release-*` / pre-staging

| + | − |
| --- | --- |
| Минимальная цена на main | Легко **пропустить** перед deploy |
| Подходит «gate перед окном» (как REL0) | Не заменяет регрессию на каждый commit |

### Сравнение

| Критерий | (A) push/PR | (B) nightly+dispatch | (C) release/manual |
| --- | --- | --- | --- |
| Стоимость минут/month | высокая | средняя | низкая |
| Задержка обнаружения | минуты | часы | по процессу |
| Защита main | сильная | средняя | слабая |
| Подходит post-REL0 (staging уже candidate) | да, после bake-in | **рекомендуется как первый шаг** | как доп. gate |

---

## 4. Рекомендация (REL1 prep)

**Фаза 1 (низкий риск):** вариант **(B)** — новый workflow `e2e-polygon-rel1.yml`, `workflow_dispatch` + nightly на `main`, `timeout-minutes: 40`, один job, последовательно polygon → classification; upload artifact report on failure.

**Фаза 2 (после 5× green nightly + 2× ручной dispatch на PR):** добавить job в **(A)** как **required** check **или** оставить nightly + обязательный dispatch в runbook перед staging window.

**Оптимизация (отдельный мини-PR, не в этом документе):** CI-only config `playwright.rel1-ci.config.ts` — один webServer block, `testMatch` оба spec, один `prepare_polygon` — экономия ~2–4 min.

---

## 5. Критерий включения (acceptance REL1-E2E)

**Обязательно (до и после включения workflow):**

1. **Два прогона подряд green** на целевом product SHA для **каждого** набора: `npm run test:e2e:polygon` и `npm run test:e2e:classification` (локально или на runner — одинаковые команды; `TEST_PG_PORT` как в окружении).
2. **Перед каждым выпуском на staging** (maintenance window): **обязательный ручной** прогон **обоих** наборов (4+7 по `--list`); результат фиксируется в листе окна (pass/fail, SHA). Nightly/dispatch в CI **не заменяет** этот шаг, пока владелец явно не скажет иное.

**Дополнительно для включения автоматического CI (фаза B/A):**

3. **GHA:** workflow (B) — **≥5** consecutive nightly **success** на `main` (после пунктов 1–2).
4. **Нет** падений из‑за `finpilot_test` pollution (guard `verify_live_finpilot_test` / truncate в prepare).
5. Владелец: явное **«REL1-E2E в CI — ok»** + выбор фазы (A/B/C).
6. Запись в `STATE.json` / `DECISIONS.md` (отдельный commit после создания workflow).

---

## 6. Предлагаемые файлы и diff (не применять)

| Действие | Файл |
| --- | --- |
| **Add** | `.github/workflows/e2e-polygon-rel1.yml` (~55 строк, копия service/steps из `e2e.yml`) |
| **Optional** | `frontend/playwright.rel1-ci.config.ts` — объединённый suite |
| **Optional** | `frontend/package.json` — `"test:e2e:rel1": "playwright test -c playwright.rel1-ci.config.ts"` |
| **Docs** | `docs/runbook-staging.md` — «перед окном: dispatch e2e-polygon-rel1» |
| **Не менять** | `playwright.config.ts` testIgnore — default 6 tests остаются быстрыми |

**Diff-скелет workflow (reference only):**

```diff
--- /dev/null
+++ b/.github/workflows/e2e-polygon-rel1.yml
@@ -0,0 +1,48 @@
+name: e2e-polygon-rel1
+
+on:
+  workflow_dispatch:
+  schedule:
+    - cron: "0 2 * * *"
+
+jobs:
+  polygon-classification:
+    runs-on: ubuntu-latest
+    timeout-minutes: 40
+    services:
+      postgres:
+        image: postgres:16.6
+        env:
+          POSTGRES_HOST_AUTH_METHOD: trust
+          POSTGRES_USER: postgres
+        ports:
+          - 5433:5432
+        options: >-
+          --health-cmd "pg_isready -U postgres"
+          --health-interval 5s
+          --health-timeout 5s
+          --health-retries 10
+    steps:
+      - uses: actions/checkout@v4
+      - uses: astral-sh/setup-uv@v5
+        with:
+          python-version: "3.12"
+      - uses: actions/setup-node@v4
+        with:
+          node-version: "24"
+          cache: npm
+          cache-dependency-path: frontend/package-lock.json
+      - name: Backend deps
+        working-directory: backend
+        run: uv sync --group dev --frozen
+      - name: Роль для миграций
+        working-directory: backend
+        run: >
+          uv run python -c "…"
+      - name: Frontend deps
+        working-directory: frontend
+        run: npm ci
+      - name: Chromium
+        working-directory: frontend
+        run: npx playwright install --with-deps chromium
+      - name: Polygon then classification E2E
+        working-directory: frontend
+        run: npm run test:e2e:polygon && npm run test:e2e:classification
+        env:
+          TEST_PG_PORT: "5433"
+          CI: "true"
+      - name: Upload report
+        if: failure()
+        uses: actions/upload-artifact@v4
+        with:
+          name: playwright-polygon-rel1-report
+          path: frontend/playwright-report/
+          retention-days: 7
```

---

## 7. Связь с STATE

- `fa_r06_rel0_acceptance.next_scope_blocked_until_owner` — **CI expansion** ждёт решения владельца; этот документ — вход для **REL1-E2E**, не автоматическое включение.
- После REL0 staging на **0016** polygon E2E проверяет **product** behaviour, не staging DB.
