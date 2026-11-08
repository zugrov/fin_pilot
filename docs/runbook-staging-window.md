# Платное окно приёмки на стенде (60–75 мин)

**Назначение:** одноразовое окно на арендованном VPS для полного прогона приёмки (API-скрипт + браузер) **без** слияния PR и **без** боевых данных клиента.

**Связанные документы:** [runbook-staging-acceptance.md](runbook-staging-acceptance.md) (сценарий и ожидания), [runbook-staging.md](runbook-staging.md) (постоянный staging, если есть).

**Плейсхолдеры (не подставлять реальные IP в git):**

| Имя | Смысл |
| --- | --- |
| `SSH_ALIAS` | Имя `Host` в `~/.ssh/config` |
| `APP_ROOT` | Каталог репозитория на сервере (например `/opt/finpilot`) |
| `LOCAL_PORT` | Локальный порт SSH-туннеля (например `18090`) |
| `REMOTE_PROXY_PORT` | Порт HTTP-прокси **на сервере** (для `docker-compose.prod` + IP override — обычно `80`) |
| `BASE_URL` | `http://127.0.0.1:LOCAL_PORT` с вашей машины |
| `WINDOW_ID` | Метка окна, например `acceptance-YYYYMMDD` |

**Ориентировочное время:** 60–75 минут (включая ожидание CI на merge-коммите заранее, оплату ЮKassa, ручной UI).

---

## а) До включения сервера — подготовка

### Контрольный список

- [ ] Ветка/образ зафиксированы (SHA из PR, теги `finpilot-api` / `finpilot-frontend` на сервере).
- [ ] **Тестовый магазин ЮKassa:** `YOOKASSA_SHOP_ID` и `YOOKASSA_SECRET_KEY` (личный кабинет → тестовый магазин, не боевой).
- [ ] **Тестовая карта:** реквизиты из [документации ЮKassa по тестовым платежам](https://yookassa.ru/developers/payment-acceptance/testing-and-going-live/testing) (успешная оплата).
- [ ] **Пароль тестовых пользователей** для `STAGING_PASSWORD` (один пароль для owner и tenant B в скрипте; в git не класть).
- [ ] Репозиторий на Mac: клон `fin_pilot`, ветка `chore/deploy-ip-stand` (или нужный SHA).
- [ ] Свободный терминал: **1** — SSH/compose на сервере, **2** — туннель (можно фон), **3** — `python3 scripts/staging_acceptance.py`.
- [ ] Каталог артефактов: `mkdir -p var/${WINDOW_ID}` (вне git).
- [ ] PR по деплою: проверки CI зелёные (`gh pr checks <номер> -R zugrov/fin_pilot`).

### Что **не** делать до окна

- Не включать `SEND_LIVE_PAYMENTS=true` с боевым магазином.
- Не коммитить `.env` и дампы в git.
- Не оставлять VPS включённым «на ночь» без дампа и выключения в панели провайдера.

---

## b) Включение стенда

На сервере (через `SSH_ALIAS`):

```bash
ssh "${SSH_ALIAS}" 'set -euo pipefail
  cd "${APP_ROOT}"
  docker compose --env-file .env \
    -f infra/docker-compose.prod.yml \
    -f infra/docker-compose.prod.ip.override.yml \
    ps'
```

Ожидание: сервисы `api`, `worker`, `beat`, `postgres`, `redis`, `proxy`, `frontend` в состоянии **running**.

Проверка health **на сервере** (loopback):

```bash
ssh "${SSH_ALIAS}" 'curl -fsS http://127.0.0.1/health/live && echo && curl -fsS http://127.0.0.1/health/ready && echo'
```

Ожидание: HTTP **200**, `{"status":"ok"}`.

---

## в) Ключи ЮKassa в `.env` на сервере

**Правила:** значения не вставлять в командную строку с пробелами (`export KEY=value` в `bash_history`), не печатать в чат/протокол. Права на файл **`chmod 600 .env`**.

### Редактирование на сервере

```bash
ssh -t "${SSH_ALIAS}" "cd '${APP_ROOT}' && cp -a .env .env.bak.${WINDOW_ID} && chmod 600 .env && \${EDITOR:-nano} .env"
```

Задать или обновить **имена** (значения — только в файле на сервере):

| Переменная | Значение для окна |
| --- | --- |
| `YOOKASSA_SHOP_ID` | id тестового магазина |
| `YOOKASSA_SECRET_KEY` | секрет тестового магазина |
| `YOOKASSA_RETURN_URL` | URL возврата после оплаты (фронт стенда, через туннель или публичный `PUBLIC_BASE_URL`) |
| `SEND_LIVE_PAYMENTS` | `true` |
| `BILLING_MODE` | `test` |

Опционально: `PUBLIC_BASE_URL` — должен совпадать с тем, что видит пользователь после редиректа с ЮKassa.

Проверка **без значений**:

```bash
ssh "${SSH_ALIAS}" "cd '${APP_ROOT}' && grep -E '^(SEND_LIVE_PAYMENTS|BILLING_MODE|YOOKASSA_SHOP_ID|YOOKASSA_SECRET_KEY|YOOKASSA_RETURN_URL)=' .env | sed 's/=.*$/=…/'"
```

Ожидание: все пять строк присутствуют; `SEND_LIVE_PAYMENTS=…`, `BILLING_MODE=…`.

### Перезапуск API и worker

```bash
ssh "${SSH_ALIAS}" 'set -euo pipefail
  cd "${APP_ROOT}"
  docker compose --env-file .env \
    -f infra/docker-compose.prod.yml \
    -f infra/docker-compose.prod.ip.override.yml \
    up -d api worker'
```

Повторить `curl` на `/health/ready` (как в §b). При ошибке — `docker compose ... logs --tail=80 api worker` (без `.env` в выводе).

---

## г) Туннель и `scripts/staging_acceptance.py`

### SSH-туннель (локально, отдельный терминал)

```bash
ssh -N -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PROXY_PORT}" "${SSH_ALIAS}"
```

Проверка с Mac:

```bash
curl -fsS "http://127.0.0.1:${LOCAL_PORT}/health/live" && echo
```

### Переменные окружения для скрипта

| Переменная | Обязательно | Комментарий |
| --- | --- | --- |
| `STAGING_BASE_URL` | да | `http://127.0.0.1:LOCAL_PORT` |
| `STAGING_PASSWORD` | нет | иначе `getpass` при запуске |
| `STAGING_BILLING_MODE` | нет | по умолчанию `checkout`; запасной — `sql` |
| `STAGING_VERIFY_TOKEN_OWNER` | после register | токен из SQL-подсказки скрипта (§2.1 acceptance runbook) |
| `STAGING_VERIFY_TOKEN_TENANT_B` | то же для tenant B | |
| `STAGING_PROVIDER_PAYMENT_ID` | опционально | id объекта ЮKassa, если не хотите вводить после оплаты |
| `STAGING_POSTGRES_EXEC_HINT` | рекомендуется | одна строка для copy-paste `psql` на сервере |

Пример hint (подставьте свой `APP_ROOT` **только у себя**, не в git):

```bash
export STAGING_POSTGRES_EXEC_HINT='ssh '"${SSH_ALIAS}"' "cd '"${APP_ROOT}"' && docker compose --env-file .env -f infra/docker-compose.prod.yml -f infra/docker-compose.prod.ip.override.yml exec -T postgres psql -U finpilot -d finpilot"'
```

### Запуск

```bash
cd /path/to/fin_pilot
export STAGING_BASE_URL="http://127.0.0.1:${LOCAL_PORT}"
export STAGING_BILLING_MODE=checkout
python3 scripts/staging_acceptance.py
```

**Шаги скрипта (кратко):**

1. Register → скрипт печатает **SQL для verify** → выполнить на сервере → ввести **токены** (getpass/env).
2. Workspace + **4 фирмы** → quote/checkout.
3. Скрипт печатает **`confirmation_url`** → открыть в браузере → оплатить **тестовой картой** ЮKassa → вернуться в терминал → **Enter**.
4. При необходимости — `provider_payment_id` (env, SQL-подсказка, getpass) → webhook → ожидание `activated=true` (до 120 с) → `activate` по фирмам.
5. Остальной сценарий (продажи, профиль, пороги, изоляция) — см. [runbook-staging-acceptance.md](runbook-staging-acceptance.md).

### Fallback на SQL

Если в отчёте есть шаг **`billing.fallback`** (503 checkout, таймаут активации, нет `provider_payment_id`):

```bash
export STAGING_BILLING_MODE=sql
python3 scripts/staging_acceptance.py
```

Выполнить напечатанный **GRANT** из `scripts/staging_grant_entitlements.sql` на сервере (роль `finpilot`) → **Enter** в скрипте. Подробности — §3.2 (в) в [runbook-staging-acceptance.md](runbook-staging-acceptance.md).

Итог скрипта: `acceptance-report.md` в корне репозитория (без секретов) — скопировать в `var/${WINDOW_ID}/`.

---

## d) Ручной проход в браузере

**10–15 мин**, тот же `BASE_URL` через туннель, пользователь после verify и оплаты слота.

Пошаговая таблица: **§10** в [runbook-staging-acceptance.md](runbook-staging-acceptance.md) (баннеры профиля, НДС, порог, мастер).

Скриншоты — только в `var/${WINDOW_ID}/`, не в git.

---

## е) Завершение окна (строгий порядок)

1. **Дамп БД** на локальную машину:

```bash
ssh "${SSH_ALIAS}" "cd '${APP_ROOT}' && docker compose --env-file .env \
  -f infra/docker-compose.prod.yml \
  -f infra/docker-compose.prod.ip.override.yml \
  exec -T postgres pg_dump -U finpilot -Fc finpilot" \
  > "var/${WINDOW_ID}/finpilot.dump"
```

2. **Проверка дампа** (локально):

```bash
pg_restore -l "var/${WINDOW_ID}/finpilot.dump" | head -20
```

3. **Копия отчёта:**

```bash
cp acceptance-report.md "var/${WINDOW_ID}/"
```

4. **Артефакты окна** (чеклист):

| Артефакт | Путь |
| --- | --- |
| Дамп PostgreSQL | `var/${WINDOW_ID}/finpilot.dump` |
| Отчёт приёмки | `var/${WINDOW_ID}/acceptance-report.md` |
| Краткий протокол (SHA, pass/fail по разделам) | `var/${WINDOW_ID}/notes.md` (создать вручную) |
| Скриншоты UI | `var/${WINDOW_ID}/screenshots/` |
| Копия `.env` | **только** в зашифрованном хранилище, **не** в git |

5. **Только после** пунктов 1–4: остановить или **удалить VPS** в панели провайдера.

> **Важно:** `docker compose down` на сервере **не** останавливает почасовую оплату VPS. Останавливают/удаляют **саму виртуальную машину** в панели провайдера.

---

## ж) Симптом → причина → действие

| Симптом | Вероятная причина | Что делать |
| --- | --- | --- |
| **502** / пустой ответ при старте | `proxy`/`api` ещё не поднялись, неверный туннель | `docker compose ps`; логи `proxy api`; проверить `LOCAL_PORT` и `REMOTE_PROXY_PORT` |
| **401** после login в UI | `SESSION_COOKIE_SECURE=true`, cookie не уходит по HTTP | Для приёмки через API — скрипт уже использует `StagingCookiePolicy`; в браузере — заходить по тому же `BASE_URL`, что в туннеле, или временно согласовать cookie-политику на стенде |
| **503** на `POST .../billing/checkout` | `SEND_LIVE_PAYMENTS=false` или нет ключей | §в; либо `STAGING_BILLING_MODE=sql` |
| Checkout OK, нет **`activated=true`** за 120 с | Worker не обрабатывает inbox | `docker compose ... ps worker`; логи worker; на сервере убедиться, что Celery beat/worker запущены; при необходимости SQL fallback |
| **402** на dashboard после SQL GRANT | SQL не выполнен, неверные UUID, период вне `now()` | Повторить GRANT; сверить `tenant_id`/`company_id` из вывода скрипта |
| Письмо verify не приходит | `SEND_REAL_EMAIL=false`, письмо в outbox | SQL по подсказке скрипта (`transactional_email_outbox`), см. [runbook-staging-acceptance.md](runbook-staging-acceptance.md) §2.1 |
| ЮKassa: отказ / не тестовый платёж | Боевой магазин или `BILLING_MODE` не `test` | Только тестовый магазин + `BILLING_MODE=test` |
| Webhook 200, но сумма не активируется | Неверный `provider_payment_id` | SQL `payment_attempts`; id из ЛК ЮKassa для тестового платежа |

---

## Быстрые ссылки

- Детальный сценарий API: [runbook-staging-acceptance.md](runbook-staging-acceptance.md)
- Переменные ЮKassa и режимы биллинга: тот же документ, **§3.2**
- Скрипт: `scripts/staging_acceptance.py`
- SQL fallback: `scripts/staging_grant_entitlements.sql`
