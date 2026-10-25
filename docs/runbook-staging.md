# Закрытый staging на общем VPS

Это частный контур для пилота, не коммерческий запуск. `infra/docker-compose.prod.yml` на этот хост не запускать: он публикует порты 80 и 443, которые уже занимает nginx хоста.

Актуальный снимок стенда (**backend FA-R02 фаза A + frontend UX-CALENDAR-01, 2026-10-21**) — в `docs/readiness-live.md`, [`docs/roadmap/FA-R02-release-phase-A.md`](roadmap/FA-R02-release-phase-A.md) и [`docs/roadmap/UX-CALENDAR-01.md`](roadmap/UX-CALENDAR-01.md). Историческая контрольная точка 2026-10-16 и restore 2026-10-17 сохранены в `readiness-live.md`.

Каталог `/fin_pilot` на VPS, Compose **`finpilot-staging`** запущен. Публичное имя `staging.maxima-consulting.ru` не заводилось. Доступ — SSH-туннель на **`127.0.0.1:8090`**.

**SSH (справочно):** alias `my-vps`; hostname VPS при read-only проверке 2026-10-23 — `iufqpatmbm`. Подключаться по alias из runbook, не по hostname.

## UX-CALENDAR-01 · frontend on staging (2026-10-21)

Frontend-only deploy. **Backend, schema, postgres, redis, proxy, api, worker, beat не пересоздавались** этим шагом.

| Поле | Значение |
|---|---|
| Frontend source SHA | `15555751aafffe1743e60107508ea3df6ca93724` |
| Tag | `finpilot-frontend:release-15555751aafffe1743e60107508ea3df6ca93724` |
| Image ID | `sha256:3330c797afceab82eb55a6ce6cdedc5912d49282c1f4bab0b7369c40aa411b56` |
| Platform | linux/amd64 |
| Bundle | `assets/index-Dh8wFLHG.js` |
| Override | `/var/tmp/finpilot-frontend-1555575/compose.frontend.override.yml` |

Содержимое override (только image frontend):

```yaml
services:
  frontend:
    image: finpilot-frontend:release-15555751aafffe1743e60107508ea3df6ca93724
```

**Compose (полный контекст для recreate frontend):**

```bash
cd /fin_pilot && docker compose \
  --env-file /fin_pilot/.env \
  -f infra/docker-compose.staging.yml \
  -f /var/tmp/finpilot-release-be9e47a/compose.override.yml \
  -f /var/tmp/finpilot-frontend-1555575/compose.frontend.override.yml \
  -p finpilot-staging \
  up -d --no-deps --no-build --pull never frontend
```

Без имени сервиса `up` **не** выполнять. `compose down`, `docker prune`, откат backend или схемы — **вне** этой процедуры.

### Откат только frontend

Образ на VPS сохранён: `finpilot-frontend:release-7ee85e5` → `sha256:a00f7ddfcb005257654b6fde15951b09e805aadde30bf6b0ad7a51c5daf84697`.

1. В `/var/tmp/finpilot-frontend-1555575/compose.frontend.override.yml` указать `image: finpilot-frontend:release-7ee85e5` (или отдельный rollback-override с тем же содержимым).
2. Тот же **полный** контекст compose, что выше, снова `up -d --no-deps --no-build --pull never frontend`.
3. Проверить `GET /health/live` и `GET /health/ready` на `127.0.0.1:8090`.

## FA-R02 фаза A · backend snapshot (2026-10-20)

| Сервис | Образ / ID |
|---|---|
| `api`, `worker`, `beat` | `finpilot-api:release-be9e47af63310f3d5745eadf67dddb0e8c6c9442`; manifest `sha256:31b6986b3102b434efc65d8d91bce48d58a1a1a78642d3799b7324e3dd652e62`; config `sha256:19f676995efe664069de0f2cd8fad84735a5e899e777ef0f0fee7d562d692f1e`; **linux/amd64**; **один beat** |
| `frontend` | в фазе A **не пересоздавался** (`release-7ee85e5`); с 2026-10-21 — см. раздел **UX-CALENDAR-01** выше |
| Schema | **`20261019_0014`** |
| Product SHA | `be9e47af63310f3d5745eadf67dddb0e8c6c9442` |

**Compose (обязательный контекст для recreate api/worker/beat):**

```bash
cd /fin_pilot && docker compose \
  --env-file /fin_pilot/.env \
  -f infra/docker-compose.staging.yml \
  -f /var/tmp/finpilot-release-be9e47a/compose.override.yml \
  -p finpilot-staging
```

Без `--env-file` interpolation `POSTGRES_PASSWORD` **ломается** (инцидент 2026-10-20). После DDL: **fail-closed** — не поднимать baseline автоматически, не делать downgrade/volume delete без отдельного решения.

**Override** задаёт safe flags: `SESSION_INGEST_ENABLED=false`, все `SEND_*` и `POLL_IMAP`/`REFUNDS` — false, `BALANCES_IMPORT_ENABLED=true`, `BILLING_MODE=test`, `EMAIL_PROVIDER_MODE=smtp`. Команды: `/app/.venv/bin/uvicorn`, `/app/.venv/bin/celery`.

**Backup freeze FA-R02 (2026-10-20, до миграции окна):** `/var/backups/finpilot/finpilot-staging-FA-R02-20261020T063211Z.tar.enc`, SHA-256 `7661414aaaa7b21fadc58508b26393e91346b1183ca924c3fc2aa95b3d2c8a90`; внутри — **`database.dump`**, manifest **`schema_before=20261017_0010`** (не schema **0014**). Offsite Mac — тот же hash. **Не** единственный reference для отката после **0016**: в окне REL0 — **`ops/rel0/rel0-backup-create.sh`** + **`ops/rel0/rel0-backup-verify.sh`** (MANIFEST, `DECISIONS.md`); порядок pause/resume — § «Копия наполненного staging» ниже; §G readiness. Probe verify на freeze 0010 — OK 2026-10-23; **backup 0014 не создавался**. Откат REL0 — backup окна + образы §G, **не** одноразовые checkpoint-скрипты 20261017.

**Ops REL0 (канон в git):** `ops/rel0/` — verify/create; Mac `rel0-artifacts/` — зеркало. **Исторические** `ops/check-restore-checkpoint.sh`, `ops/finish-restore-checkpoint.sh` (20261017, untracked) — drill checkpoint **20261016**, **не** согласованная процедура отката REL0.

**Rollback images (на диске):** api `sha256:d5520080a1cd6c731bcdee102ca00dfa0098622c076b58e6ea2946b1cacd55ae`; worker/beat `sha256:c7ff510499579c8e95ade8e11036a86f4ac91c55bdaac0714e2a30d1e23d490c`.

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

## Флаги на контрольной точке

Наблюдение процесса api 2026-10-16, без значений секретов. Это не разрешение что-либо включать или выключать.

`APP_ENV=production`, `EMAIL_PROVIDER_MODE=smtp`, `SEND_REAL_EMAIL=true`, `SEND_EXTERNAL_MESSAGES=false`, `SEND_LIVE_PAYMENTS=true`, `POLL_IMAP=false`, `REFUNDS_ENABLED=false`, `BILLING_MODE=test`, `RECEIPT_MODE` пустой. `BILLING_GUARD_BYPASS` не задан. Списки получателей, SMTP, магазин ЮKassa и токен бота заданы. Webhook из репозитория не регистрируется.

Фирма ООО «Топ» не live, поэтому боевой платёж при `BILLING_MODE=test` не проводится. Платёжный клиент при этом подключён. Письмо на адрес из списка может уйти, потому что почтовый флаг включён. Новые письма и платежи без отдельного решения не создавать.

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
- `YOOKASSA_SHOP_ID`, `YOOKASSA_SECRET_KEY`, `YOOKASSA_RETURN_URL`, `YOOKASSA_IP_ALLOWLIST`
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`
- `BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`

В `.env.example` платёжные, почтовые и ботовые значения пустые. На стенде 2026-10-16 магазин, SMTP, токен бота и списки получателей заданы. Значения в документ не переносятся.
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

На этом VPS у worker видны родитель и два дочерних процесса. Это наблюдение одного запуска, не отдельный нагрузочный прогон. На macOS prefork по-прежнему не доказан.

## Health

- `GET /health/live` отвечает `{"status":"ok"}` без базы.
- `GET /health/ready` выполняет `SELECT 1` и отвечает `{"status":"ok"}`.
- Через proxy те же пути доступны как `/health/live` и `/health/ready`.
- Готовность Redis, worker и beat эти маршруты не проверяют.
- После появления имени стенда те же пути проверяются через него. Порты 80 и 443 остаются у nginx хоста.

## Копия наполненного staging

Выполнена 2026-10-16. Повторный дамп, шифрование и перенос этим разделом не запускаются.

`backend/scripts/backup.py` отвергает базу `finpilot`. `backend/scripts/restore.py` удаляет и создаёт заново только `finpilot_restore`. Оба скрипта для этой копии не вызывать. Существующую `finpilot_restore` не перезаписывать и не удалять.

Фактический результат:

1. На время дампа и съёма пяти файлов тома `finpilot-staging_imports` остановлены только api, worker и beat. Postgres, Redis, proxy и frontend не останавливались. Те же api, worker и beat запущены снова в `2026-10-16T18:50:55Z`, без пересборки и без `--force-recreate`.
2. Custom-дамп снят из контейнера Postgres. Пароль остался внутри контейнера.
3. Пять вложений сняты отдельным контейнером с тома только для чтения. В остановленный api заходить было нельзя.
4. Архив зашифрован `openssl enc -aes-256-cbc -pbkdf2 -salt`. Пароль брался из временного файла оператора. В `.env` приложения, в документ и в git он не записывался.
5. Незашифрованные временные файлы и файл пароля удалены после проверки расшифровки. В PostgreSQL эта проверка архив не восстанавливала.
6. `health/live` и `health/ready` после возврата сервисов отвечали 200.

Файл на VPS: `/var/backups/finpilot/finpilot-staging-20261016.tar.enc`, 327712 байт, режим 600. SHA-256: `084e91d3a82b6034d578a39324437a4d664197b9e75ac699a4124053f73d163b`. Внутри custom-дамп `finpilot`, архив вложений и манифест. Код манифеста `0449e8dc262c03d604b1ebeedc66e27471e22b88`, миграция `20261014_0009`. Redis и `.env` в архив не входили.

Внешняя копия подтверждена 2026-10-17. На Mac, вне репозитория, файл `/Users/maximzugrov/Backups/finpilot-staging/finpilot-staging-20261016.tar.enc`: 327712 байт, режим 600, `shasum -a 256` дал тот же SHA-256.

Для восстановления этой копии нужны, без записи их значений:

- пароль архива у оператора;
- роль и пароль, которыми выполняется `pg_restore`;
- пароли ролей `finpilot_app` и `finpilot_worker`, если проверка идёт отдельным подключением этих ролей;
- `SECRET_ENCRYPTION_KEY`, если нужно читать зашифрованные учётные данные источников;
- файл `.env` стенда для сверки имён. Восстановленную базу этим файлом не запускать.

## Проверка восстановления

Выполнена 2026-10-17 на текущем PostgreSQL. Приложение, worker и beat на проверочную базу не переключались. Сервисы не останавливались и не пересоздавались. Внешние письма, Telegram, платежи и IMAP не включались. Повторный запуск скриптов этим разделом не разрешён. Базу `finpilot_checkpoint_20261016` и каталог вложений не удалять.

Локальные скрипты в репозиторий этим описанием не входят:

| Скрипт | SHA-256 | Что сделал |
|---|---|---|
| `ops/check-restore-checkpoint.sh` | `4d0de1ed919dbe5c2456ee60ca5207d45173496f08ede11dafcf543d0961ba73` | Один запуск. Дамп восстановлен в новую базу. Код 1: сравнение текстового `t`/`f` с выводом `psql` `true`/`false`. Повторно не запускался |
| `ops/finish-restore-checkpoint.sh` | `724a048eeecf53d8476c0747cce8cde56c059c7d06a1d62bfc6d6af97b33c426` | Завершил проверку уже существующей базы. Успешный запуск вернул код 0 |

Первая попытка до остановки напечатала `APP_PYTHON_OK`, `CONTROLS_OK` и `SCHEMA_RLS_OK`. База `finpilot_checkpoint_20261016` получила OID 20388. Каталог вложений тогда не создавался. Права ролей не менялись. Временная расшифровка и файл пароля той попытки удалены.

У `finish-restore-checkpoint.sh` один запуск остановился до расшифровки, потому что каталога файла пароля на VPS не было. База и архив от этого не изменились. Следующий запуск того же файла, с тем же SHA-256, вернул код 0 и напечатал `APP_PYTHON_OK`, `CONTROLS_OK`, `SCHEMA_OK`, `APP_ROLE_OK`, `ATTACHMENTS_OK`. `CREATE DATABASE`, `DROP DATABASE` и `pg_restore` этот скрипт не выполнял.

Сохранено:

- база `finpilot_checkpoint_20261016`, OID 20388;
- пять файлов в `/var/backups/finpilot/attachments-checkpoint-20261016`;
- `finpilot` OID 16384 и `finpilot_restore` OID 18391;
- архив с SHA-256 `084e91d3a82b6034d578a39324437a4d664197b9e75ac699a4124053f73d163b`.

Временный каталог `/var/backups/finpilot/restore-decrypt-20261016` отсутствует. Файл пароля успешного запуска удалён. `health/live` и `health/ready` отвечали 200.

Роли этого PostgreSQL уже существовали. Проверка не доказывает восстановление на новом сервере: там роли, пароли и политики нужно создать заново и пройти отдельно.

## Откат

Остановить и удалить только контейнеры и тома проекта `finpilot-staging`. Сайты nginx `maxima-consulting.ru`, `cfo`, `agent` и `grill`, их контейнеры и DNS не менять. Новый сайт `staging` убрать отдельным файлом.

Откат схемы командой `alembic downgrade` не является процедурой стенда. Если миграция уже применена, откат данных — копия этой базы, не `scripts/restore.py`.
