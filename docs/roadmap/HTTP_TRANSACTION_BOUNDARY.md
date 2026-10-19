# HTTP transaction boundary (FA-R02.1b)

**Статус:** accepted 2026-10-19, product SHA `a78080a6c072ea851db9fa2d458cb0983af5a76a`.

**Snapshot vs deploy.** Принятый код в репозитории — `a78080a…`. Staging deployed baseline
`7ee85e501735efcfa449ad8f44ef11258e5e4cf2` — R02.1, миграции 0011/0012 и transaction boundary
**не** заявлены как применённые на staging.

## Контракт

- Все production HTTP handlers `/api/v1/*` получают БД через **`DbSession`** =
  `Annotated[Session, Depends(get_db, scope="function")]`.
- **`get_db`**: создать Session → `yield` → **`commit`** при нормальном завершении →
  **`rollback`** при исключении из handler/sub-deps → **`close`** в `finally`.
- **FastAPI 0.143.0**, **`scope="function"`**: teardown generator (commit/close) выполняется
  **после** path handler, но **до** `http.response.start` клиенту.
- Default `scope="request"` для yield-deps откладывал commit **после** ответа — класс дефекта
  (runtime на POST wallet до R02.1; закрыт infra FA-R02.1b для текущего HTTP graph).
- **POST wallet:** локальный `session.commit()` в handler **снят**; единственный финальный
  request commit — `get_db`.

## Покрытие маршрутов

| Область | Кол-во |
|---------|--------|
| OpenAPI-операций (всего) | **100** |
| `/api/v1/*` на `DbSession` | **98** |
| `/health/live` | без БД |
| `/health/ready` | отдельная Session в handler (`main.py`), не dependency graph |

Не утверждать, что **каждый** из 96 API endpoints отдельно проверен runtime ASGI-probe;
покрытие — статический guard + перечисленные integration probes.

## Regression (фактически на a78080a)

**Unit guard:** `tests/unit/test_http_db_dependency_guard.py` — `DbSession` + `scope=function`,
нет bare `Depends(get_db)` в v1, OpenAPI 98 ops.

**ASGI `http.response.start` + независимое чтение БД:**

- POST wallet create (и адаптированные тесты в `test_wallet_response_commit.py`);
- POST opening balance;
- POST transaction create (+ idempotency record);
- POST revenue create (+ idempotency record);
- POST balances import commit (+ `opening_balances`);
- POST YooKassa webhook (+ `billing_webhook_inbox`);
- GET auth/me (+ `last_seen_at`).

**Commit failure (5xx, без успешного 2xx start):** wallet create; transaction create.
**Webhook duplicate:** YooKassa `IntegrityError` без существующего inbox → 5xx
(`test_yookassa_webhook_integrity_error_without_duplicate_is_not_ok`).

## Workflows (product SHA a78080a)

| Run | Результат |
|-----|-----------|
| CI 39218808186 | **341 passed**, **0 skipped**; Ruff/Mypy green; frontend **89** unit + build |
| E2E 39218808291 | **6 passed** |

Полный backend pytest **локально не выполнялся** (недоступная test DB на агенте приёмки);
результаты CI/E2E других SHA сюда не переносятся.

## История product-коммитов (без squash)

| SHA | Назначение |
|-----|------------|
| `bacf02f` | docs: приёмка FA-R02.1 (baseline docs перед infra) |
| `4f5eb72` | **fix:** `DbSession`, webhooks duplicate fix, regression tests (product) |
| `f257b6f` | **test:** корректные payload transaction/revenue; unpack `_ready` balances; `TestClient(raise_server_exceptions=False)` для 5xx — **только test setup**, не смена контракта |
| `6824a92` | **test:** balances CSV (`BAL_HEADER`); commit-failure через TestClient вместо ASGI — **probe/setup** |
| `a78080a` | **test:** probe balances commit по `opening_balances` на response.start — **уточнение probe**, не изменение HTTP boundary |

Принятый product snapshot: **`a78080a…`**.

## Commit failure

- Исключение при финальном `commit` → rollback, проброс → **нет** успешного `response.start`
  с 2xx; клиент получает **5xx** (без SQL/credentials).

## Webhooks

- Inbox до 200; duplicate `IntegrityError` → 200 только при доказанном повторе в inbox.
- Активация подписки, Celery, payload policy — без изменений.

## Остаточные риски

- **Закрыто FA-R02.1b:** commit-after-response для текущего `/api/v1` graph через `scope=function`.
- **Открыто:** новые endpoints → `DbSession` + guard + review; streaming/background + Session;
  внешние side effects; Celery lifecycle; **не** равно «готовность к реальному пилоту».

## Связь с FA-R02.1

- FA-R02.1 **accepted**, SHA `9fe5c06d8778b56556baa40932aa189c231696c1` (transport + точечный
  wallet commit на момент R02.1). FA-R02.1b **не** переписывает accepted SHA R02.1.
