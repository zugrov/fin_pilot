# Архитектура

Версия документа: 1.0. Соответствует ТЗ v2.0.

## Форма системы

Модульный монолит. Один процесс API, отдельные процессы worker и единственный beat. Микросервисов нет. Пилот рассчитан на один VPS.

```
браузер / Telegram
        |
      Caddy          наружу только proxy
     /     \
frontend   api (FastAPI)
              |
         services  ---- integrations (ЮKassa, SMTP, IMAP, Telegram)
              |
         repositories
              |
         PostgreSQL 16          Redis 7 (очереди, rate limit; не source of truth)
              ^
         worker / beat (Celery)
```

Web и бот читают одни и те же services. Отдельного финансового ядра для канала нет.

## Слои

| Слой | Путь | Ответственность |
|---|---|---|
| API | `backend/app/api` | HTTP, cookies, CSRF, коды ошибок. Не считает деньги. |
| Domain | `backend/app/domain` | Формулы и инварианты без БД и HTTP. |
| Services | `backend/app/services` | Сценарии: регистрация, активация оплаты, guard. |
| Repositories | `backend/app/repositories` | Запросы SQLAlchemy. |
| Models | `backend/app/models` | Таблицы. |
| Integrations | `backend/app/integrations` | Внешние адаптеры за интерфейсом. |
| Jobs | `backend/app/jobs` | Celery-задачи. Вызывают services, не дублируют правила. |
| Security | `backend/app/security` | Пароли, сессии, RBAC, billing guard. |
| Observability | `backend/app/observability` | request_id, логи без секретов. |

Services не импортируют HTTP- и bot-handlers. Вызовы внешних API не выполняются внутри длинной финансовой транзакции: сначала запись в inbox/outbox, затем отдельная транзакция обработки.

## Деньги

- Python: `Decimal`. Float в домене запрещён.
- PostgreSQL: `NUMERIC(20,2)` для сумм, `NUMERIC(12,6)` для процентов.
- API: суммы строками (`"2500.00"`).
- Округление денег: `ROUND_HALF_UP` до копейки.
- `Number` допустим только для графиков, не для денежных итогов. Итоги считает backend.

## Два контура

Billing продавца SaaS и финансовый контур клиента разделены.

- Оплата подписки создаёт `Invoice`, `PaymentAttempt`, `BillingPeriod`, `CompanyEntitlement`.
- Она не создаёт `CashTransaction` и `RevenueEntry` клиента.
- Учётные данные магазина ЮKassa принадлежат SaaS. Клиент и frontend не подменяют `shop_id`.

## Изоляция

Каждый request, job, callback и send проверяет: аутентификацию, подтверждённый email, membership, RBAC, company entitlement и `paid_through`. Проверка по часам, даже если задача истечения не отработала.

RLS на таблицах с `tenant_id`: `SET LOCAL` в транзакции, роль приложения без `BYPASSRLS`. Идентификаторы клиента не доверены: чужой UUID даёт 404.

## Поток оплаты

```
quote (серверная цена)
  -> оферта и invoice
  -> PaymentAttempt + Idempotence-Key
  -> hosted checkout ЮKassa
  -> return URL показывает «ожидает проверки» и не открывает доступ
  -> webhook только в inbox, ответ 200
  -> worker GET платежа у провайдера
  -> сверка суммы, валюты, shop, test, metadata
  -> одна DB-активация на invoice
```

Без учётных данных интеграция выключена. Успех не подделывается.

## Флаги внешних действий

| Переменная | Default | Смысл |
|---|---|---|
| `SEND_REAL_EMAIL` | `false` | Письма остаются в outbox, SMTP не вызывается |
| `SEND_EXTERNAL_MESSAGES` | `false` | Telegram не отправляется |
| `SEND_LIVE_PAYMENTS` | `false` | Создание живого платежа запрещено |
| `BILLING_MODE` | `test` | Test-платёж не активирует live-tenant |
| `EMAIL_PROVIDER_MODE` | `mock` | В тестах mock-провайдер |

Реальные письма, сообщения, платежи и возвраты выключены до явного разрешения. Webhook в проде не регистрируется этим репозиторием автоматически.

## Что сознательно не в этапах 0–2

Кошельки, операции, импорт, выручка, прогноз, бюджеты, алерты, Telegram, IMAP. Их инварианты зафиксированы в `accounting-policy.md` и `slices-plan.md`, чтобы последующие этапы не переписывали ядро.
