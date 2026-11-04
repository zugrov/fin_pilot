# Runbook · контур B (пилот ТОПКОМ) — **plan-only**

**Статус:** план, **без исполнения** до отдельного окна владельца (целевая готовность VPS **2026-11-06**).  
**Не** деплоить из этого документа автоматически; каждый шаг с ID — только после явного «ок» по списку (как REL0).

**Контекст:** D6 **принят** — **вариант B** (отдельный контур), провайдер **≠** текущий staging (Beget). Staging остаётся **синтетика** (ООО «Топ»). Реальные данные **ООО «ТОПКОМ»** — **запрещены** до закрытия юридических предпосылок (L1–L4, ведёт владелец) и успешной **пробы восстановления** на новом сервере (`baseline.restore_new_server_verified` в STATE — **false** до прогона).

**Ссылки:** [`DECISIONS.md`](roadmap/DECISIONS.md), [`STATE.json`](roadmap/STATE.json) · `pilot_topkom_d6`, `ops/rel0/`, [`runbook-staging.md`](runbook-staging.md), `infra/docker-compose.prod.yml` (шаблон compose; на окне — override как у staging REL0).

---

## 0. Окна разрешений владельца (отдельные «ок»)

| Окно | Что разрешает | Что **не** разрешает |
| --- | --- | --- |
| **W0 · подготовка VPS** | B-01…B-06, hardening, Docker | compose postgres volume, данные ТОПКОМ |
| **W1 · restore probe** | B-07…B-11 (синтетика REL0, одноразовый Postgres) | боевой том, api/worker в prod-сети |
| **W2 · deploy контура B** | B-12…B-22 @ зафиксированный **`SHA`** окна | загрузка реальных данных ТОПКОМ |
| **W3 · реальные данные** | FA-R10.1, L1–L4 closed, отдельное письменное «ок» | автоматически из deploy |

Юридические L1–L4 и deploy **не** считаются выполненными, пока в STATE не зафиксирован отдельный факт прогона (сейчас **не** зафиксирован).

---

## 1. Требования к серверу и доступам

| Требование | Критерий |
| --- | --- |
| ОС | Linux LTS (Ubuntu 24.04 или аналог), **РФ** (локализация данных) |
| Ресурсы (мин.) | 4 vCPU, 8 GiB RAM, 80 GiB SSD + отдельный том под Postgres (рекомендуется) |
| SSH | Только **ключ**; пользователь **`deploy`** (не root); **PermitRootLogin no** |
| Firewall | `ufw`/security group: 22 **с ограничением по IP**, 80/443 для Caddy |
| fail2ban | Включён для sshd |
| Обновления | Unattended security updates или еженедельное окно patch |
| Время | `Europe/Moscow`, NTP синхронизирован |
| Docker | Engine + Compose plugin (версии зафиксировать в окне) |

Секреты и passphrase backup — **только** менеджер паролей / offline; **не** git, **не** чат.

**SSH / firewall (B-02, B-03):**

1. Перед `PasswordAuthentication no` — **вторая** SSH-сессия под `deploy` + **веб-консоль провайдера** (запасной вход).
2. Зафиксировать **`ADMIN_IP`** (или /32 VPN). При **динамическом IP** — VPN / временное правило / security group провайдера; не полагаться только на `ufw allow OpenSSH` без `from`.
3. Порядок: `ufw allow from ${ADMIN_IP}/32 to any port 22 proto tcp` → `ufw allow 80,443/tcp` → проверить **новый** SSH-вход → **`ufw enable`** → только потом закрывать первую сессию.
4. Откат: консоль провайдера → `ufw disable` / восстановление `sshd_config` из бэкапа.

---

## 2. Состав стека

Docker Compose (project **`finpilot-contour-b`**, файл на базе `infra/docker-compose.prod.yml` + override окна) — **только фаза (b)**, не раньше W2:

| Сервис | Образ / версия | Назначение |
| --- | --- | --- |
| **postgres** | `postgres:16.6-bookworm` (как prod) | БД `finpilot`, **именованный volume** |
| **redis** | pin minor (как prod) | Celery broker |
| **api** | `finpilot-api:release-candidate-<SHA>` | HTTP API |
| **worker** / **beat** | тот же api-образ | Celery |
| **frontend** | `finpilot-frontend:release-candidate-<SHA>` | SPA |
| **proxy** | Caddy pin (как staging/prod) | TLS, reverse proxy |

TLS: Let's Encrypt или загруженный сертификат на **выделенном домене** контура B (не staging-домен).

### 2.1 Переменные и флаги (контур B, **безопасные defaults**)

Согласовано с [`runbook-staging.md`](runbook-staging.md) и `.env.example` на **`SHA` окна**:

| Переменная | Значение контура B |
| --- | --- |
| `APP_ENV` | `production` |
| `SEND_REAL_EMAIL` | **false** до окна с настроенным SMTP и allowlist |
| `SEND_EXTERNAL_MESSAGES` | **false** |
| `SEND_LIVE_PAYMENTS` | **false** |
| `POLL_IMAP` | **false** |
| `REFUNDS_ENABLED` | **false** |
| `CLASSIFICATION_PACKS_ENABLED` | **false** (default) |
| `FA_R03_LOCAL_RECONCILIATION_ENABLED` | **false** |
| `SESSION_COOKIE_SECURE` | **true** |
| `BILLING_MODE` | **`test`** на пилоте B до отдельного решения на **live** |
| `BILLING_GUARD_BYPASS` | **не задавать** — **запрещён** |
| `EMAIL_PROVIDER_MODE` | **`smtp`** (не `mock` при `APP_ENV=production`) |
| `MAIL_QUARANTINE_ENABLED` | **false** |

`DATABASE_URL` / `WORKER_DATABASE_URL` — роли **`finpilot_app`** / **`finpilot_worker`** (создаёт миграция). **`MIGRATION_DATABASE_URL`** — отдельная роль миграций; **только** для one-shot `alembic`, не для api/worker.

### 2.2 Активация tenant / firm / слота (**без** SQL и bypass)

Поддерживаемые **HTTP**-шаги (см. `backend/app/api/v1/auth.py`, `billing.py`, `companies.py`):

1. `POST /api/v1/auth/register` → письмо verify в outbox.
2. `POST /api/v1/auth/verify-email` с **`token`** из ссылки письма (обязателен для дальнейших действий).
3. Создание workspace / firm через product API (роли membership).
4. `POST /api/v1/billing/checkout` при **`BILLING_MODE=test`** и тестовых `YOOKASSA_*` → entitlement / `paid_through` по [`billing-policy.md`](billing-policy.md) (**без** `BILLING_GUARD_BYPASS`).
5. Firm **`draft`** → активное использование только при entitlement и `paid_through`.

Запрещено: SQL-правки, `BILLING_GUARD_BYPASS`, второй слот и данные ТОПКОМ до FA-R10.1 / W3.

---

## 3. Доставка артефактов (до B-07)

| Вариант | Суть |
| --- | --- |
| **(a) REL0-канал** *(рекомендуется)* | CI tarball **`finpilot-api-release-candidate-${SHA}`** / frontend + compose override + `ops/rel0/*` + `MANIFEST.sha256`; scp/rsync; `sha256sum -c` |
| **(b) Read-only deploy-ключ** | checkout **`SHA`** + те же tarball образов (git **не** заменяет образы) |

**`SHA` окна** — единый для: MANIFEST, тегов образов, **`ALEMBIC_HEAD`** (из allowlist CI / `STATE` окна). Не смешивать образ и alembic-ревизии с разных commit.

---

## 4. Первый пользователь и smoke (**production** + `BILLING_MODE=test`)

| Путь | Условия | Статус preflight |
| --- | --- | --- |
| **A · Register + verify + billing** | `SEND_REAL_EMAIL=true`, `EMAIL_PROVIDER_MODE=smtp`, `OUTBOUND_EMAIL_ALLOWLIST`, тестовый YooKassa; API как в §2.2 | **Поддерживается продуктом** |
| **B · Smoke на БД после restore backup** | Если в дампе уже есть пользователи «Топ» — нужны **учётные данные окна** (не в git); иначе путь A | Зависит от сценария deploy |
| **C · «Админ без SQL» при `SEND_REAL_EMAIL=false`** | Публичного API выдачи verify-token **нет**; invite тоже ставит outbox | **Блокер продукта** — см. §13 |

**Рекомендация:** для W2 smoke — **A** (временно SMTP + allowlist на домен B) **или** restore синтетического backup на **боевой** том с заранее согласованным логином окна. **Не** обещать «процедуру B» без SMTP/SQL — её в коде нет.

---

## 5. Резервные копии

| Параметр | Политика (предложение) |
| --- | --- |
| Формат | `ops/rel0/rel0-backup-create.sh` → `*.tar.enc` |
| Расписание | Ежедневно + перед окнами |
| Offsite | Вне VPS, **30** суток rolling |
| RPO / RTO | **24 ч** / **8 ч** (пилот) |

**Preflight:** `rel0-backup-create.sh` и `rel0-backup-verify.sh` в git **жёстко привязаны** к `finpilot-staging-postgres-1`, пути `/var/backups/finpilot/*.tar.enc`, БД `finpilot_rel0_probe` — см. §13 перед B-20 / probe.

---

## 6. Фазы развёртывания

```text
(a) probe: одноразовый Postgres, restore REL0, migrate head на probe, baseline
(b) deploy: postgres volume → ready → migrate → api/worker/beat/frontend/proxy
(c) health/smoke синтетика
(d) реальные данные ТОПКОМ — только W3
```

### Фаза (a)

**Артефакт:** `finpilot-staging-REL0-20261028T081545Z.tar.enc`  
**SHA-256:** `57fe4b435d201f5c370a17ff39b16b5ba570f8f519aa1848e7048674f2cbaa1a`  
**MANIFEST внутри архива:** `schema_before=20261022_0016`, baseline «Топ» (контрольные суммы как в `rel0-backup-verify.sh`).

**Postgres пробы:** контейнер **`${PROBE_PG}`**, **без** compose-volume `finpilot-contour-b_*`. Пользователь/роль **`finpilot`** + пароль как в `.env` окна (дамп staging). Порт **`127.0.0.1:5434`**.

**Критерии:**

- После restore: `alembic_version` = **`20261022_0016`**.
- После **`alembic upgrade head`** на **той же** probe-БД: version = **`ALEMBIC_HEAD`** для **`SHA`**; baseline «Топ» **не изменился** (сравнить SQL-агрегаты до/после B-10).
- Cleanup B-11: DROP probe DB, `docker stop/rm ${PROBE_PG}`, wipe decrypt dir.

### Фаза (b)

Порядок как [`runbook-staging.md`](runbook-staging.md): **postgres (+ redis) → ready → migrate → остальные сервисы**. Не запускать api/worker до успешной миграции на боевой БД.

---

## 7. Команды (plan-only)

Параметры: `HOST`, `DEPLOY_USER=deploy`, `PASSFILE`, **`SHA`**, `ALEMBIC_HEAD` (из MANIFEST окна, напр. `20261027_0017`), `PROBE_DB=finpilot_contour_b_probe`, `PROBE_PG=finpilot-probe-pg`, `SCHEMA_BEFORE=20261022_0016`, `ADMIN_IP`, `DOMAIN`.

| ID | Действие | Шаблон | Ожидание | Откат |
| --- | --- | --- | --- | --- |
| **B-01** | SSH check | `ssh deploy@${HOST} 'uname -a; timedatectl'` | Moscow TZ | — |
| **B-02** | sshd hardening | см. §1; **2 сессии** + консоль | ключ OK | sshd backup |
| **B-03** | ufw | `allow from ${ADMIN_IP}/32` → 22; 80,443; **enable после 2-й сессии** | SSH жив | ufw off / консоль |
| **B-04** | fail2ban | jail sshd | работает | stop |
| **B-05** | Docker | pin CE + compose plugin | `docker compose version` | — |
| **B-06** | каталоги | `/fin_pilot`, `/var/backups/finpilot`, `/var/tmp/finpilot-rel0-artifacts` | права deploy | rm empty |
| **B-07** | артефакты **SHA** | REL0 (a): compose override, `ops/rel0`, MANIFEST; backup `.enc` в `/var/backups/finpilot/` | sha256 OK; **нет** compose pg volume | rm artifacts |
| **B-07a** | **load api image** | `docker load` ← `finpilot-api-release-candidate-${SHA}` | образ для **alembic** и deploy | rmi |
| **B-08** | probe Postgres + restore | `docker run -d --name ${PROBE_PG} -e POSTGRES_USER=finpilot -e POSTGRES_PASSWORD=… -e POSTGRES_DB=postgres -p 127.0.0.1:5434:5432 postgres:16.6-bookworm` (**без** `-v` compose); restore по шагам verify (decrypt, `pg_restore` в `${PROBE_DB}`) — **list_id**, не слепой вызов verify.sh без адаптации §13 | restore OK; baseline file **до** migrate | B-11 |
| **B-09** | schema_before | `SELECT version_num FROM alembic_version` | **`20261022_0016`** | B-11 |
| **B-10** | **migrate на probe** | One-shot **только** probe URL: `docker run --rm --network host -e MIGRATION_DATABASE_URL=postgresql+psycopg://finpilot:…@127.0.0.1:5434/${PROBE_DB} finpilot-api:release-candidate-${SHA} uv run alembic upgrade head` — **запрет** URL с боевым `postgres` service | `version_num` = **`ALEMBIC_HEAD`**; baseline «Топ» = B-08 | B-11 |
| **B-11** | cleanup probe | DROP `${PROBE_DB}`; `docker stop/rm ${PROBE_PG}`; rm decrypt tmp | нет probe/pg volume | — |
| **B-12** | load frontend | `docker load` frontend tarball | image OK | rmi |
| **B-13** | `.env` | 600, §2.1; **без** bypass | Settings OK | restore |
| **B-14** | postgres+redis only | `docker compose -p finpilot-contour-b up -d postgres redis` | **первое** создание pg volume | down |
| **B-15** | readiness | `pg_isready` / `SELECT 1` на сервис `postgres` | ready | logs |
| **B-16** | migrate **боевой** | One-shot: `MIGRATION_DATABASE_URL` → **только** compose postgres (`finpilot` DB); тот же образ **`SHA`** | `alembic_version` = head | restore B-20 |
| **B-17** | full stack | `docker compose … up -d` (api, worker, beat, frontend, proxy) | containers up | down |
| **B-18** | TLS | Caddy / LE | HTTPS | revert Caddyfile |
| **B-19** | health | `curl …/health/ready` | 200 | — |
| **B-20** | smoke | login §4 + read cashflow (синтетика) | 200 | — |
| **B-21** | backup | `rel0-backup-create.sh` **после адаптации** §13 | `.enc` + sha256 | delete bad |
| **B-22** | offsite | rsync `.enc` + `.sha256` offsite | sha match | — |
| **B-23** | rollback drill | откат на N-1 **`SHA`** (документировано) | health OK | re-up |

---

## 8. Откат и аварийное восстановление

1. Stop traffic (DNS / Caddy).
2. `compose down` (контур B).
3. Restore verified `.enc` (процедура verify после адаптации ops).
4. Предыдущий образ **`SHA`**, health, smoke.

---

## 9. Минимальный мониторинг

| Область | Минимум |
| --- | --- |
| Доступность | Внешний check `/health/ready` |
| Диск | >85% — алерт |
| Backup | Нет `.enc` за 26 ч или verify fail |
| Логи | 14–30 сут.; **без** ПДн, тел писем, назначений, выгрузок 1С |

---

## 10. Удаление данных клиента (план, после W3)

По запросу оператора ТОПКОМ и юридическому «ок»: maintenance → удаление/анонимизация firm в БД по FA-R10 / договору → offsite backup по retention. **Не** исполнять до появления данных и L1–L4.

---

## 11. Входы от владельца (2026-11-06+)

| # | Вход |
| --- | --- |
| 1–8 | *(как ранее: провайдер, IP, SSH, домен, backup, passphrase, L1–L4, S10/S11)* |
| 9 | Доставка кода: **(a) REL0** или **(b) deploy-key** |
| 10 | Почта: SMTP+DNS **или** явный сценарий smoke §4 |
| 11 | **`BILLING_MODE=test`**, без bypass |
| 12 | **`SHA` + `ALEMBIC_HEAD`** окна W2 (из CI allowlist) |
| 13 | **`ADMIN_IP`** / VPN для SSH (§1) |

---

## 12. Ограничения

- Plan-only; не создаёт tenant/платёж/webhook без окна.
- Приоритет у `ops/rel0/` в git над этим текстом при расхождении.

---

## 13. Блокеры preflight (PR #4) — **не исполнение**

| ID | Блокер | Влияние | Предлагаемая задача |
| --- | --- | --- | --- |
| **BLK-1** | `rel0-backup-verify.sh` / `rel0-backup-create.sh`: фикс. `PG_CONTAINER=finpilot-staging-postgres-1`, `CHECK_DB=finpilot_rel0_probe`, compose staging | Probe/backup на контуре B **не** запускать «как на staging» без **list_id** / параметризации | **ops:** env `PG_CONTAINER`, `CHECK_DB`, `COMPOSE_PROJECT` для контура B |
| **BLK-2** | Verify-скрипт **DROP** probe DB в конце | Нельзя вызывать полный verify **до** B-10 migrate; нужен restore-only list_id или fork | **ops:** `rel0-backup-restore-only.sh` или флаг «skip drop» |
| **BLK-3** | Alembic до load api (исправлено в runbook: **B-07a** перед B-10) | — | Следовать порядку B-07a → B-10 |
| **BLK-4** | Первый пользователь при `SEND_REAL_EMAIL=false` | Нет API для verify-token | **FA-R10.1-ops:** SMTP+allowlist **или** product bootstrap (не SQL) |
| **BLK-5** | Compose override контура B | В repo только `infra/docker-compose.prod.yml`; override как у staging — **артефакт окна** | Подготовить override в list_id W2 |
| **BLK-6** | `restore_new_server_verified` | Остаётся **false** до успешного W1 на VPS | После W1 — запись в STATE отдельным docs-коммитом |

**Merge PR #4 (docs):** допустим — документы и блокеры согласованы.  
**Исполнение W0–W2:** **не готово** до закрытия **BLK-1**, **BLK-2**, **BLK-4** (минимум) и list_id владельца.
