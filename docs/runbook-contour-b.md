# Runbook · контур B (пилот ТОПКОМ) — **plan-only**

**Статус:** план, **без исполнения** до отдельного окна владельца (целевая готовность VPS **2026-11-06**).  
**Не** деплоить из этого документа автоматически; каждый шаг с ID — только после явного «ок» по списку (как REL0).

**Контекст:** D6 **принят** — **вариант B** (отдельный контур), провайдер **≠** текущий staging (Beget). Staging остаётся **синтетика** (ООО «Топ»). Реальные данные **ООО «ТОПКОМ»** — **запрещены** до закрытия юридических предпосылок (L1–L4, ведёт владельца) и успешной **пробы восстановления** на новом сервере.

**Ссылки:** [`DECISIONS.md`](roadmap/DECISIONS.md), [`STATE.json`](roadmap/STATE.json) · `pilot_topkom_d6`, `ops/rel0/`.

---

## 1. Требования к серверу и доступам

| Требование | Критерий |
| --- | --- |
| ОС | Linux LTS (Ubuntu 24.04 или аналог), **РФ** (локализация данных) |
| Ресурсы (мин.) | 4 vCPU, 8 GiB RAM, 80 GiB SSD + отдельный том под Postgres (рекомендуется) |
| SSH | Только **ключ**; пользователь **`deploy`** (не root); **PermitRootLogin no** |
| Firewall | `ufw`/security group: 22 (ограничить по IP владельца), 80/443 только для Caddy |
| fail2ban | Включён для sshd |
| Обновления | Unattended security updates или еженедельное окно patch |
| Время | `Europe/Moscow`, NTP синхронизирован |
| Docker | Engine + Compose plugin (версии зафиксировать в окне) |

Секреты и passphrase backup — **только** менеджер паролей / offline; **не** git, **не** чат.

**SSH / firewall (B-02, B-03):** перед `PasswordAuthentication no` и **`ufw enable`** открыть **вторую** SSH-сессию под `deploy` и убедиться, что вход по ключу работает; держать **веб-консоль провайдера** как запасной вход. Если IP владельца **динамический** — заранее согласовать диапазон / VPN / временное правило `ufw`, иначе можно потерять доступ. **`ufw enable` только после** успешного входа во второй сессии.

---

## 2. Состав стека

Docker Compose (отдельный project name, напр. `finpilot-contour-b`) — **только фаза (b)**, не раньше:

| Сервис | Образ / версия | Назначение |
| --- | --- | --- |
| **postgres** | `postgres:16.6` | БД `finpilot`, **именованный volume** (боевой контур) |
| **redis** | `redis:7` (pin minor) | Celery broker |
| **api** | `finpilot-api:release-candidate-<SHA>` | HTTP API |
| **worker** | тот же api-образ | Celery worker |
| **beat** | тот же api-образ | Celery beat |
| **frontend** | `finpilot-frontend:release-candidate-<SHA>` | SPA |
| **caddy** | официальный pin | TLS termination, reverse proxy |

TLS: Let's Encrypt или загруженный сертификат на **выделенном домене** контура B (не staging-домен).

### 2.1 Переменные и флаги (контур B, **безопасные defaults**)

| Переменная | Значение контура B |
| --- | --- |
| `APP_ENV` | `production` |
| `SEND_REAL_EMAIL` | **false** (до отдельного решения и настроенного SMTP) |
| `SEND_EXTERNAL_MESSAGES` | **false** |
| `SEND_LIVE_PAYMENTS` | **false** |
| `POLL_IMAP` | **false** |
| `REFUNDS_ENABLED` | **false** |
| `CLASSIFICATION_PACKS_ENABLED` / product flag | **false** |
| `FA_R03_LOCAL_RECONCILIATION_ENABLED` | **false** (в production код **запрещает** true) |
| `SESSION_COOKIE_SECURE` | **true** |
| `BILLING_MODE` | **`test`** на пилоте контура B, пока нет отдельного решения на **live** и боевой кассы; при `live` — только с проверенным webhook и без обходов |
| `BILLING_GUARD_BYPASS` | **не задавать** / **false** — **запрещён** |
| `EMAIL_PROVIDER_MODE` | **`smtp`** при реальном SMTP; до выбора провайдера письма не отправлять (`SEND_REAL_EMAIL=false`) |
| `MAIL_QUARANTINE_ENABLED` | **false** (до отдельного решения) |

Полный список — из `.env.example` / `app/config.py` на **зафиксированном SHA main** окна.

### 2.2 Активация tenant / firm / слота (**без** `BILLING_GUARD_BYPASS`)

Порядок только через продукт и биллинг (см. `docs/billing-policy.md`, `docs/decision-log.md`):

1. Регистрация tenant и **подтверждение email** (нужен рабочий канал из § «Первый пользователь»).
2. Подписка и **оплата / тестовый entitlement** в выбранном `BILLING_MODE` (`test` — тестовый магазин, без live webhook в этом runbook).
3. Создание firm в **`draft`**, затем переход в активное использование только при **entitlement** и актуальном **`paid_through`** (или эквивалент для test-режима по политике).
4. **Не** создавать второй слот, **не** загружать данные ТОПКОМ и **не** включать финансовые флаги до отдельного окна FA-R10.1.
5. SQL-правки прав, ручной `owner_confirmed` и обходы guard — **запрещены** (D5, DECISIONS).

---

## 3. Доставка артефактов на сервер (выбор до B-07)

| Вариант | Суть | Плюсы / минусы |
| --- | --- | --- |
| **(a) REL0-канал** | Tarball образов api/frontend с CI + `docker-compose` override + каталог `ops/rel0/` + `MANIFEST.sha256` с commit окна; доставка scp/rsync/offsite, сверка SHA | **Рекомендуется:** повторяет staging REL0, не нужен git на VPS, воспроизводимые SHA |
| **(b) Deploy-ключ read-only** | `git fetch && git checkout ${SHA}` в `/fin_pilot`; образы всё равно **load** из CI tarball | Удобно для hotfix-дiff; риск drift, нужен guard на read-only ключ |

**Рекомендация владельцу:** **(a)** для первого разворота контура B; **(b)** — только если зафиксированы политика ключа и тот же SHA образов, что в MANIFEST окна.

---

## 4. Первый пользователь и подтверждение email

**Решение за владельцем** до включения `SEND_REAL_EMAIL=true`.

| Вариант | Описание | Риски |
| --- | --- | --- |
| **A · SMTP контура B** | Отдельный SMTP (или транзакционный провайдер) в `.env`, `EMAIL_PROVIDER_MODE=smtp`, SPF/DKIM на домене B | OPEX, настройка DNS; без этого регистрация «зависнет» на verify |
| **B · Админ-процедура** | Утверждённый runbook: одноразовая выдача доступа через **поддерживаемый** product/API путь (invite / reset), **без** SQL и без `BILLING_GUARD_BYPASS` | Нужен явный документ «кто и когда»; риск human error |

**Рекомендация:** для контура B с **`BILLING_MODE=test`** и **`SEND_REAL_EMAIL=false`** на старте — **B** для первого smoke (учётная запись создаётся в окне с владельцем по процедуре), параллельно готовить **A** до FA-R10.1. **Не** использовать mock-email в `APP_ENV=production`.

---

## 5. Резервные копии

| Параметр | Политика (предложение) |
| --- | --- |
| Формат | Encrypted tarball (`*.tar.enc`) по канону `ops/rel0/rel0-backup-create.sh` |
| Расписание | Ежедневно + перед каждым окном изменений |
| Хранение | **Вне** VPS (offsite: объектное хранилище / Mac владельца), срок **30** суток rolling |
| Целостность | SHA-256 в sidecar; периодическая `rel0-backup-verify.sh` |
| RPO (пилот) | **24 ч** (ежедневный backup) |
| RTO (пилот) | **8 ч** (ручное восстановление + smoke) |

---

## 6. Порядок развёртывания (фазы)

```text
(a) probe-restore синтетики REL0 (одноразовый Postgres, без боевого тома)
    → (b) deploy contour B @ SHA (именованный том postgres)
    → (c) health/smoke синтетика
    → (d) отдельное решение о реальных данных ТОПКОМ
```

**Важно:** шаги **B-12+** (load образов, compose с **postgres volume**) — **не раньше** успешной фазы **(a)** и явного «ок» на фазу **(b)**.

### Фаза (a) — проба восстановления (синтетика)

**Артефакт:** `finpilot-staging-REL0-20261028T081545Z.tar.enc`  
**SHA-256:** `57fe4b435d201f5c370a17ff39b16b5ba570f8f519aa1848e7048674f2cbaa1a` (см. DECISIONS · REL0).  
**MANIFEST внутри backup:** `schema_before=20261022_0016`, baseline «Топ».

**Postgres для пробы (не боевой):** одноразовый контейнер **без** именованного тома compose, данные только в контейнере / `--tmpfs` (см. B-08, B-11).

**Критерий успеха probe:**

- БД `finpilot_contour_b_probe` на **probe Postgres** (порт localhost, не сервис compose).
- После restore: `alembic_version` = **`20261022_0016`** (= `schema_before` MANIFEST копии).
- После **`alembic upgrade head`** на той же копии: `alembic_version` = **head** репозитория окна (в т.ч. проверка **0017** на данных); контрольные суммы baseline «Топ» **не изменились** относительно снимка сразу после restore.
- После OK — cleanup B-11 (DROP DB, stop/rm probe container, wipe decrypt dir).

### Фаза (b) — разворот контура

Образы и `ops/` по каналу §3; миграции на **боевой** БД один раз через `MIGRATION_DATABASE_URL` (если БД пустая — `upgrade head`; если restore — по политике окна).

### Фаза (c) — health и smoke

- `/health/live`, `/health/ready` → 200
- Авторизованный smoke на **синтетической** firm (не ТОПКОМ), без загрузки клиентских файлов.

### Фаза (d) — реальные данные

**Только** после: L1–L4 closed владельцем, `restore_new_server_verified=true` на probe, отдельное письменное «ок» на загрузку ТОПКОМ.

---

## 7. Команды (plan-only, для пошагового одобрения)

Параметры: `HOST` — IP контура B; `DEPLOY_USER=deploy`; `PASSFILE` — путь к passphrase backup (600); `SHA` — product main; `PROBE_DB=finpilot_contour_b_probe`; `PROBE_PG=finpilot-probe-pg`; `SCHEMA_BEFORE=20261022_0016` (из MANIFEST backup REL0-20261028); `PROBE_PORT=127.0.0.1:5434`.

| ID | Действие | Команда (шаблон) | Ожидаемый результат | Откат |
| --- | --- | --- | --- | --- |
| **B-01** | Проверка SSH | `ssh ${DEPLOY_USER}@${HOST} 'uname -a && timedatectl'` | Linux, timezone Moscow | — |
| **B-02** | Hardening sshd | В **новой** сессии: `PermitRootLogin no`, `PasswordAuthentication no` + reload sshd; **первая** сессия открыта | root/password login denied; deploy по ключу OK | restore sshd config backup; консоль провайдера |
| **B-03** | Firewall base | После **второй** успешной SSH-сессии: `ufw allow OpenSSH`, `ufw allow 80,443/tcp`, **`ufw enable`** | только нужные порты; вход по SSH сохранён | `ufw disable` / консоль |
| **B-04** | fail2ban | установка пакета + jail sshd | banned после N fails | stop fail2ban |
| **B-05** | Docker install | по доке Docker CE pin version | `docker compose version` OK | remove packages |
| **B-06** | Каталог приложения | `sudo install -d -o deploy -m 750 /fin_pilot` (+ `/var/tmp/finpilot-rel0-artifacts` при варианте (a)) | владелец deploy | `rm -rf` (если пусто) |
| **B-07** | Доставка SHA | **(a)** scp tarball образов + compose + `ops/rel0/*`; `sha256sum -c MANIFEST.sha256` **или (b)** read-only git checkout `${SHA}` + те же tarball образов | MANIFEST OK; **не** создавать compose postgres volume | удалить artifacts |
| **B-08** | Probe Postgres + decrypt | `docker run --rm -d --name ${PROBE_PG} -e POSTGRES_HOST_AUTH_METHOD=trust -p ${PROBE_PORT}:5432 postgres:16.6` (**без** `-v` compose); затем `rel0-backup-verify.sh` / restore в `${PROBE_DB}` на `${PROBE_PORT}` | **`REL0_BACKUP_VERIFY_OK`**; **нет** volume `finpilot-contour-b_*` | B-11 |
| **B-09** | Probe schema_before | `SELECT version_num FROM alembic_version` в `${PROBE_DB}` | **`20261022_0016`** (= MANIFEST `schema_before` копии) | B-11 |
| **B-10** | Probe migrate head | `alembic upgrade head` (one-shot, `DATABASE_URL` → probe) | `version_num` = repo **head** (0017+); **0017** на данных без ошибки | B-11 |
| **B-11** | Probe baseline + cleanup | Read-only контроль «Топ» = эталон REL0 **до и после** B-10; затем `DROP DATABASE`, `docker stop/rm ${PROBE_PG}`, wipe decrypt dir | диск без сырого dump; probe container gone | — |
| **B-12** | Load api image | `docker load` из tarball CI `finpilot-api-release-candidate-${SHA}` | image present | `docker rmi` |
| **B-13** | Load frontend image | аналогично frontend artifact | image present | `docker rmi` |
| **B-14** | `.env` contour B | файл 600, owner deploy, флаги §2.1–2.2 | валидация Settings OK | restore prev .env |
| **B-15** | Migrate (боевой том) | `alembic upgrade head` через one-shot → **compose postgres volume** | one row in alembic_version | restore from backup (B-20) |
| **B-16** | Compose up | `docker compose -p finpilot-contour-b up -d` (**первое** создание postgres volume) | all healthy | `compose down` (volume — осознанно) |
| **B-17** | TLS | Caddy obtains cert для домена B | HTTPS valid | revert Caddyfile |
| **B-18** | Health | `curl -fsS https://${DOMAIN}/health/ready` | 200 | logs |
| **B-19** | Smoke synthetic | scripted login + cashflow read | 200, known synthetic totals | — |
| **B-20** | Backup post-deploy | `rel0-backup-create.sh ${PASSFILE}` | `.tar.enc` + sha256 | delete bad backup |
| **B-21** | Offsite copy | scp/rsync `.enc` + `.sha256` offsite | sha256 match | — |
| **B-22** | Rollback drill | документированный откат образов на N-1 SHA | health OK на prev | re-up current |

---

## 8. Откат и аварийное восстановление

1. Остановить трафик (Caddy maintenance / DNS).
2. `docker compose down` (контур B).
3. Restore последнего **verified** `.tar.enc` в новую/ту же БД (как REL0 verify).
4. Поднять предыдущий известный-good образ (тег сохранять при каждом окне).
5. Health + smoke synthetic → решение о reopen.

---

## 9. Минимальный мониторинг (пилот)

| Область | Минимум |
| --- | --- |
| Доступность | Внешний HTTP(S) check `/health/ready` (интервал 1–5 мин), алерт при 2–3 fail подряд |
| Диск | Алерт при **>85%** на томе Postgres и на `/` |
| Backup | Алерт, если **нет** успешного `.tar.enc` за **26 ч** или verify/sha256 fail |
| Логи | Retention **14–30** суток на VPS; ротация docker/json; **не** логировать тела писем, назначения платежей, полные выгрузки 1С, пароли, токены, содержимое вложений |
| Инциденты | Канал владельца (email/Telegram без ПДн клиента в тексте алерта) |

---

## 10. Удаление данных клиента (план)

По запросу оператора (ТОПКОМ) и после юридического «ок»:

1. Зафиксировать tenant/firm id и срок в журнале окна (без ПДн в git).
2. Остановить worker/beat для tenant (maintenance), блокировать вход пользователей firm.
3. Удалить или анонимизировать данные firm в БД по процедуре FA-R10 / договору поручения (вложения, import batches, outbox).
4. Удалить offsite backup **только** по политике срока и отдельному списку (encrypted копии могут иметь retention 30 дней).
5. Подтверждение владельцу: список таблиц/объёмов агрегированно, без выгрузки ПДн в чат.

До утверждения L1–L4 **не** загружать реальные данные — раздел для исполнения после появления данных.

---

## 11. Что нужно от владельца к **2026-11-06**

| # | Вход |
| --- | --- |
| 1 | Провайдер контура B (договор, регион РФ) |
| 2 | Публичный **IP** VPS |
| 3 | SSH-пользователь + **публичный** ключ для `deploy` |
| 4 | Домен (или поддомен) для TLS контура B |
| 5 | Offsite-хранилище backup (bucket/path) |
| 6 | Passphrase backup в менеджере паролей (не в чат) |
| 7 | Подтверждение: юридические L1–L4 в работе; **данные ТОПКОМ не грузить** до отдельного окна |
| 8 | Выгрузки **S10/S11** (и при необходимости S9) за **2026-08** и **2026-09** → локально `var/` |
| 9 | **Способ доставки кода на VPS:** **(a) REL0 tarball + MANIFEST** *(рекомендуется)* или **(b) read-only deploy-ключ** |
| 10 | **Почта контура B:** SMTP-провайдер + DNS **или** утверждённая админ-процедура первого пользователя (§4) |
| 11 | **`BILLING_MODE`:** **`test`** для пилота B до отдельного решения на live; без `BILLING_GUARD_BYPASS` |

---

## 12. Ограничения документа

- Не создаёт tenant, firm, платёж, webhook, миграцию без окна.
- Не регистрирует боевой webhook YooKassa / IMAP.
- Не заменяет `ops/rel0/` — при расхождении приоритет у скриптов и MANIFEST в git.
