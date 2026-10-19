# HTTP transaction boundary (FA-R02 infra)

## Контракт

- Все production HTTP handlers `/api/v1/*` получают БД через **`DbSession`** =
  `Annotated[Session, Depends(get_db, scope="function")]`.
- **`get_db`**: создать Session → `yield` → **`commit`** при нормальном завершении →
  **`rollback`** при исключении из handler/sub-deps → **`close`** в `finally`.
- **`scope="function"`** (FastAPI 0.143+): teardown generator (commit/close) выполняется
  **после** path handler, но **до** `http.response.start` клиенту.
- Default `scope="request"` для yield-deps откладывал commit **после** ответа — это
  и был класс дефекта (доказан на POST wallet до infra-пакета).

## Покрытие маршрутов

- **98** OpenAPI-операций (включая `/health/live`, `/health/ready`).
- **96** операций `/api/v1/*` — через `DbSession` / `get_db(scope="function")`.
- **Исключения:** `/health/live` (без БД); `/health/ready` — отдельная Session в
  handler (`main.py`), не HTTP dependency graph.

## Commit failure

- Исключение при финальном `commit` → rollback, проброс наверх → **нет** успешного
  `response.start` с 2xx; клиент получает безопасный **5xx** (без SQL/credentials).
- Поведение «handler вернул 200, commit упал после отправки» для `/api/v1` **не**
  является целевым контрактом при `scope="function"`.

## Webhooks

- **YooKassa:** inbox (`save_webhook`) должен быть **flush/commit в request txn до 200**.
- **Duplicate:** `IntegrityError` → rollback → **200 только если** запись inbox уже
  есть (доказанный повтор); иначе ошибка (5xx), не «всегда 200».
- Payload/signature policy, активация подписки, Celery — без изменений в этом пакете.

## Ограничения

- Гарантия — **DB-транзакция request scope**, не откат внешнего платежа/письма/Telegram.
- Provider idempotency и outbox/worker architecture не перестраивались.
- **`StreamingResponse` / `BackgroundTasks` с request Session** — не используются;
  при добавлении нужен отдельный design review.

## Regression

- Unit guard: `tests/unit/test_http_db_dependency_guard.py`.
- Integration probes: `tests/integration/test_http_transaction_boundary.py`,
  `tests/integration/test_wallet_response_commit.py`.
- Полный backend pytest + frontend unit/build + E2E FA-R01.

## Связь с FA-R02.1

- FA-R02.1 (**accepted**, SHA `9fe5c06…`) — transport + точечный wallet commit.
- Infra follow-up **FA-R02.1b** — общий boundary; **не** меняет accepted SHA R02.1.
