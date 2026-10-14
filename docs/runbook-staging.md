# Закрытый staging на общем VPS

Это частный контур для пилота, не коммерческий запуск. Этот документ описывает файлы репозитория. Каталог на VPS, DNS, nginx и контейнеры этим шагом не создаются. `infra/docker-compose.prod.yml` на этот хост не запускать: он публикует порты 80 и 443, которые уже занимает nginx хоста.

Имена переменных взяты из `.env.example`. Значения секретов в репозиторий не кладутся и здесь не приводятся.

## Сервисы

Файл: `infra/docker-compose.staging.yml`. Имя проекта Compose: `finpilot-staging`.

| Сервис | Образ | Роль |
|---|---|---|
| `postgres` | `postgres:16.6-bookworm` | Свой том `pgdata`, база `finpilot`. Пароль только из `POSTGRES_PASSWORD` |
| `redis` | `redis:7.4.2-alpine` | Свой том `redis-data`. Не источник истины и не общая очередь с другими проектами |
| `api` | сборка `backend/Dockerfile`, тег `finpilot-api:staging` | `uvicorn app.main:app` на порту 8000 внутри сети Compose |
| `worker` | тот же образ | `celery -A app.jobs.celery_app:celery_app worker` |
| `beat` | тот же образ | один `celery beat` |
| `frontend` | сборка `frontend/Dockerfile`, тег `finpilot-frontend:staging` | nginx со статикой |
| `proxy` | `caddy:2.8.4-alpine` | `infra/Caddyfile`. На хост публикуется только `127.0.0.1:8090:80` |

PostgreSQL, Redis, API, worker, beat и frontend наружу не публикуются. Вложения лежат в своём томе `imports` на `/app/var/imports` у `api` и `worker`. Чужие тома, Postgres и Redis не используются.

`infra/Caddyfile` слушает `:80` внутри контейнера и отдаёт `/api/*` и `/health/*` в API, остальное во frontend. TLS на этом Caddy нет: сертификат, когда имя будет заведено, остаётся у nginx хоста.

## Закрытие снаружи

Регистрация в приложении открыта. Пока отдельного приглашения нет, стенд закрывает nginx хоста, не код приложения.

Отдельным шагом после подтверждения, новым файлом сайта, не правя `maxima-consulting.ru`, `cfo`, `agent` и `grill`:

- A-запись `staging.maxima-consulting.ru` на этот VPS
- `server_name staging.maxima-consulting.ru`
- `proxy_pass` на `http://127.0.0.1:8090`
- базовая авторизация или фильтр по IP до этого `location`

Без этого пароля или фильтра регистрация с публичного имени недоступна быть не может: приложение само список приглашённых не проверяет.

`TRUST_PROXY=true`, когда API видит адрес клиента только через этот nginx и внутренний Caddy.

## Флаги, которые остаются выключенными

`SEND_REAL_EMAIL=false`, `SEND_EXTERNAL_MESSAGES=false`, `SEND_LIVE_PAYMENTS=false`, `POLL_IMAP=false`, `REFUNDS_ENABLED=false`, `BILLING_MODE=test`, `RECEIPT_MODE` пустой. `BILLING_GUARD_BYPASS` не задаётся. ЮKassa, Telegram и SMTP этим запуском не подключаются. Webhook из репозитория не регистрируется.

`APP_ENV=production` запрещает `EMAIL_PROVIDER_MODE=mock` и секрет сессии по умолчанию. Для закрытого staging допустимы `APP_ENV=production` и `EMAIL_PROVIDER_MODE=smtp` при `SEND_REAL_EMAIL=false`: worker тогда не вызывает SMTP. Пустой `BOT_TOKEN` старт не роняет, пока отправка выключена.

## Получатели до включения отправки

Пустой список закрывает боевую отправку. Mock-тесты этот список не используют.

- `OUTBOUND_EMAIL_ALLOWLIST` — адреса через запятую. При `SEND_REAL_EMAIL=true` адрес вне списка отменяет строку outbox с причиной `recipient` и SMTP не вызывается. Пустой список не пропускает никого.
- `TELEGRAM_CHAT_ALLOWLIST` — целые chat id через запятую. `BotApiTelegram.send` для id вне списка возвращает `failed` / `recipient` и HTTP не вызывает. Пустой список не пропускает никого. `MockTelegram` в тестах не проверяет список.
- `POLL_IMAP` остаётся `false`, пока ящик выписок отделён от `SMTP_FROM`. Это разные контуры: служебная почта и почтовый источник выписок.

Флаги отправки не включать, пока нужные адреса и chat id не записаны в `.env` на сервере.

## Переменные

Файл `.env` лежит только на сервере, вне git. Обязательные имена:

- `APP_ENV`, `PUBLIC_BASE_URL`, `CORS_ORIGINS`
- `DATABASE_URL`, `WORKER_DATABASE_URL`, `MIGRATION_DATABASE_URL`
- `REDIS_URL`, `RATE_LIMIT_BACKEND`
- `SESSION_SECRET`, `SECRET_ENCRYPTION_KEY`, `SESSION_COOKIE_SECURE`
- `POSTGRES_PASSWORD`
- `TRUST_PROXY`
- `ANNUAL_BILLING_ENABLED`, `ANNUAL_DISCOUNT_PERCENT` — скидка 15% уже в коде, клиент её не задаёт
- `OUTBOUND_EMAIL_ALLOWLIST`, `TELEGRAM_CHAT_ALLOWLIST`
- `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `YOOKASSA_RETURN_URL`, `YOOKASSA_IP_ALLOWLIST` — пустые
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` — пустые
- `BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET` — пустые
- `POLL_IMAP=false`
- `IMPORT_STORAGE_DIR=var/imports` и лимиты импорта из `.env.example`
- `BACKUP_PASSPHRASE` — только в окружении процедуры копии, не в `.env` приложения

`DATABASE_URL` внутри сети Compose указывает на сервис `postgres` этого проекта, не на чужой контейнер. Роли `finpilot_app` и `finpilot_worker` создаёт миграция. `MIGRATION_DATABASE_URL` использует отдельную роль миграций.

## Порядок будущего запуска

1. Ещё раз проверить свободное место. Если образы не помещаются, остановиться. Чужие образы и контейнеры не удалять и не перезапускать.
2. Клонировать `https://github.com/zugrov/fin_pilot` в новый каталог `/fin_pilot`. Файл `.env` создать только на сервере.
3. Собрать образы из `infra/docker-compose.staging.yml`. Теги: `finpilot-api:staging` и `finpilot-frontend:staging`.
4. Поднять только `docker compose -p finpilot-staging -f infra/docker-compose.staging.yml`.
5. Один раз применить миграции к новой базе этого проекта до `20261014_0009`.
6. Проверить `GET /health/live` и `GET /health/ready` на `127.0.0.1:8090`.
7. Данные заказчика до health и первой копии не загружать.

Worker на Linux с prefork этим репозиторием не проверен. На macOS prefork падает до тела задачи.

## Health

- `GET /health/live` отвечает `{"status":"ok"}` без базы.
- `GET /health/ready` выполняет `SELECT 1` и отвечает `{"status":"ok"}`.
- Через proxy те же пути доступны как `/health/live` и `/health/ready`.
- Готовность Redis, worker и beat эти маршруты не проверяют.
- После появления имени стенда те же пути проверяются через него. Порты 80 и 443 остаются у nginx хоста.

## Копия

`backend/scripts/backup.py` и `backend/scripts/restore.py` отвергают базу `finpilot` и порт 5432. Восстановление скрипт принимает только в `finpilot_restore`. Для базы стенда их не вызывать.

Отдельная команда копии, когда она будет согласована: custom-формат `pg_dump` базы этого проекта, том `imports`, шифрование `openssl enc -aes-256-cbc -pbkdf2`, пароль из `BACKUP_PASSPHRASE`. Хранение вне VPS. Redis не копируется.

## Откат

Остановить и удалить только контейнеры и тома проекта `finpilot-staging`. Сайты nginx `maxima-consulting.ru`, `cfo`, `agent` и `grill`, их контейнеры и DNS не менять. Новый сайт `staging` убрать отдельным файлом.

Откат схемы командой `alembic downgrade` не является процедурой стенда. Если миграция уже применена, откат данных — копия этой базы, не `scripts/restore.py`.
