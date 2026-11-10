# Окно деплоя на стенд · PR #25 (rate limit, приёмка, compose override)

> **Актуальный комбинированный runbook (PR #25 + migrate `20261110_0022` + `20261111_0023`):** [runbook-staging-window-pr25-0022-0023.md](runbook-staging-window-pr25-0022-0023.md).

**Назначение:** плановое окно выката на VPS **уже слитого** пакета [PR #25](https://github.com/zugrov/fin_pilot/pull/25) (squash → `c34328f…`) и проверки пунктов, которые в STATE остаются **не проверенными** на последней сборке.

**Команды ниже — только для копирования. Агент/CI их не выполняет.**

**Базовый runbook окна:** [runbook-staging-window.md](runbook-staging-window.md).  
**Сценарий приёмки:** [runbook-staging-acceptance.md](runbook-staging-acceptance.md).

---

## Версии (git)

| Объект | SHA / ссылка |
| --- | --- |
| **Merge PR #25** (код rate limit, scripts, override) | `c34328f1873c636c4c23f5eb1e545cdc774e585f` |
| **main на момент подготовки runbook** (включая docs) | `6873b8f9c9f8ba702f3eb0aeca32d85e4a39fcf6` |
| Что выкатывать на стенд | **main** ≥ `c34328f` (достаточно содержимого #25; docs-only коммиты после merge опциональны) |

Перед окном: `git fetch && git checkout main && git pull` на сервере в `APP_ROOT`; убедиться, что `git rev-parse HEAD` ≥ `c34328f`.

---

## Scope PR #25 (что должно оказаться на стенде)

- `TRUST_PROXY`, `TRUSTED_PROXY_CIDRS=172.18.0.0/16` (реальный IP клиента за Caddy).
- Caddy: **без** `header_up -X-Forwarded-For`, мешающего upstream XFF.
- `scripts/staging_acceptance.py`, runbook acceptance/window.
- `infra/docker-compose.prod.deploy.override.yml`, `infra/stand-patches/xlrd_stub`.
- Запрет **`FLUSHDB`** на Redis (см. runbook) — только точечный `DEL` по ключу rate limit.

---

## Предусловия

- [ ] CI **main** на выбранном SHA — **success** (backend, frontend, playwright).
- [ ] Владелец назначил **WINDOW_ID** (например `pr25-deploy-YYYYMMDD`).
- [ ] Плейсхолдеры из [runbook-staging-window.md](runbook-staging-window.md): `SSH_ALIAS`, `APP_ROOT`, `LOCAL_PORT`, `REMOTE_PROXY_PORT`, `BASE_URL`.
- [ ] Тестовый магазин ЮKassa, `STAGING_PASSWORD`, туннель — как в базовом runbook.
- [ ] **Не** использовать боевой магазин и **не** загружать данные клиента / ТОПКОМ.

---

## Порядок шагов (высокий уровень)

1. **До окна:** зелёный CI; бэкап текущего `.env` на сервере (вне git).
2. **На сервере:** `git pull` → checkout нужного SHA → `docker compose` с **тремя** override (см. базовый runbook).
3. **Пересборка:** `api` (и при смене фронта — `frontend`), `worker` после смены env.
4. **Проверка health:** `/health/live`, `/health/ready` на loopback сервера.
5. **Туннель** с Mac → `staging_acceptance.py`.
6. **Доп. проверки PR #25** (§ «Не проверено» ниже): tenant B, webhook IP.
7. **Ручной UI** (10–15 мин) по §10 acceptance runbook.
8. **Завершение:** дамп БД, отчёт в `var/${WINDOW_ID}/`, остановка VPS (базовый runbook §е).

---

## Команды (не выполнять из CI)

### Обновление кода на сервере

```bash
ssh "${SSH_ALIAS}" 'set -euo pipefail
  cd "${APP_ROOT}"
  git fetch origin
  git checkout main
  git pull
  git rev-parse HEAD'
```

Ожидание: SHA ≥ `c34328f…`.

### Compose up (с override PR #25)

```bash
ssh "${SSH_ALIAS}" 'set -euo pipefail
  cd "${APP_ROOT}"
  docker compose --env-file .env \
    -f infra/docker-compose.prod.yml \
    -f infra/docker-compose.prod.ip.override.yml \
    -f infra/docker-compose.prod.deploy.override.yml \
    up -d --build api worker beat frontend proxy'
```

### Проверка env rate limit / proxy

```bash
ssh "${SSH_ALIAS}" 'cd "${APP_ROOT}" && grep -E "^(TRUST_PROXY|TRUSTED_PROXY_CIDRS)=" .env | sed "s/=.*$/=…/"'
```

Ожидание: обе переменные заданы; CIDRS включает `172.18.0.0/16` (или согласованную подсеть docker).

### Health

```bash
ssh "${SSH_ALIAS}" 'curl -fsS http://127.0.0.1/health/live && echo && curl -fsS http://127.0.0.1/health/ready'
```

### Туннель и приёмка (локально)

```bash
ssh -N -L "${LOCAL_PORT}:127.0.0.1:${REMOTE_PROXY_PORT}" "${SSH_ALIAS}"

export STAGING_BASE_URL="http://127.0.0.1:${LOCAL_PORT}"
export STAGING_BILLING_MODE=checkout
python3 scripts/staging_acceptance.py
```

---

## Проверки до деплоя

| Проверка | PASS |
| --- | --- |
| SHA на сервере ≥ `c34328f` | да |
| Файлы override из git на диске | да |
| `.env` не в git, `chmod 600` | да |
| Нет планов `FLUSHDB` | да |

---

## Проверки после деплоя

| Проверка | PASS | FAIL |
| --- | --- | --- |
| Health 200 | ok json | логи `api`/`proxy` |
| Register rate limit по **реальному** IP, не `172.18.0.x` | ключи Redis `register:<client-ip>` | Caddy/XFF/TRUST_PROXY |
| `staging_acceptance.py` owner сценарий | exit 0, отчёт без FAIL | см. acceptance runbook |
| **Tenant B** изоляция (404 чужой dashboard) | HTTP 404 | 200/403 — блокер приёмки PR #25 |
| **Webhook ЮKassa** после тестовой оплаты | 200, активация; в логах IP не только proxy | сверить XFF + `resolve_client_ip` |
| Изоляция tenant A vs B в скрипте | шаги PASS | остановка по скрипту |

Детали tenant B и billing — [runbook-staging-acceptance.md](runbook-staging-acceptance.md).

### Не проверено на предыдущей сборке (цели этого окна)

1. **Tenant B** register/verify/dashboard isolation на **последнем** образе после `c34328f`.
2. **Вебхук ЮKassa** с определением **реального** IP через `X-Forwarded-For` при первой реальной (тестовой) оплате в checkout-режиме.

Зафиксировать в `var/${WINDOW_ID}/notes.md`: `tenant_b: PASS|FAIL`, `webhook_ip: PASS|FAIL|skip`.

---

## Откат

| Ситуация | Действие |
| --- | --- |
| Неверный compose / api не стартует | `git checkout <предыдущий-SHA>` + `up -d --build api` |
| Сломан rate limit / массовый 429 | Точечно `redis-cli DEL 'register:<ip>'` — **не** FLUSHDB |
| Биллинг / webhook | `STAGING_BILLING_MODE=sql` + GRANT по acceptance runbook |
| Критический FAIL | Остановить приёмку; оставить VPS для логов; не выгружать в prod |

Предыдущий SHA зафиксировать в протоколе окна до `git pull`.

---

## Критерии PASS / FAIL окна

**PASS** — все обязательны:

- Деплой SHA ≥ `c34328f`, health зелёный.
- Owner acceptance script — без критичных FAIL.
- Tenant B isolation — **PASS**.
- Webhook + IP — **PASS** или обоснованный **skip** (только checkout не делали) с планом повтора.
- Артефакты в `var/${WINDOW_ID}/`, дамп снят.

**FAIL** — любой из:

- Health не 200 после разумного ожидания.
- Массовый 429 на регистрации из-за неверного IP/proxy.
- Tenant B видит чужой dashboard.
- Webhook не активирует слот при корректной тестовой оплате.
- Использован `FLUSHDB` / утечка секретов в протокол.

После **FAIL** — не обновлять STATE `deployed`/`accepted` для infra-staging-rate-limit без решения владельца.

---

## Связанные записи

- STATE: `infra-staging-rate-limit`, PR #25.
- [runbook-staging.md](runbook-staging.md) — постоянный staging.
- Юридический контур реальных данных: **D5/D6**, не этот runbook.
