# Runbook · контур B (пилот ТОПКОМ) — **plan-only**

**Статус:** план, **без исполнения** до отдельного окна владельца (целевая готовность VPS **2026-11-06**).  
**Не** деплоить из этого документа автоматически; каждый шаг с ID — только после явного «ок» по списку (как REL0).

**Контекст:** D6 **принят** — **вариант B** (отдельный контур), провайдер **≠** текущий staging (Beget). Staging остаётся **синтетика** (ООО «Топ»). Реальные данные **ООО «ТОПКОМ»** — **запрещены** до закрытия юридических предпосылок (L1–L4, ведёт владелец) и успешной **пробы восстановления** на новом сервере.

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

---

## 2. Состав стека

Docker Compose (отдельный project name, напр. `finpilot-contour-b`):

| Сервис | Образ / версия | Назначение |
| --- | --- | --- |
| **postgres** | `postgres:16.6` | БД `finpilot`, отдельный volume |
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
| `SEND_REAL_EMAIL` | **false** |
| `SEND_EXTERNAL_MESSAGES` | **false** |
| `SEND_LIVE_PAYMENTS` | **false** |
| `POLL_IMAP` | **false** |
| `REFUNDS_ENABLED` | **false** |
| `CLASSIFICATION_PACKS_ENABLED` / product flag | **false** |
| `FA_R03_LOCAL_RECONCILIATION_ENABLED` | **false** (в production код **запрещает** true) |
| `SESSION_COOKIE_SECURE` | **true** |
| `BILLING_GUARD_BYPASS` | **false** |
| `MAIL_QUARANTINE_ENABLED` | **false** (до отдельного решения) |

Полный список — из `.env.example` / `app/config.py` на **зафиксированном SHA main** окна.

---

## 3. Резервные копии

| Параметр | Политика (предложение) |
| --- | --- |
| Формат | Encrypted tarball (`*.tar.enc`) по канону `ops/rel0/rel0-backup-create.sh` |
| Расписание | Ежедневно + перед каждым окном изменений |
| Хранение | **Вне** VPS (offsite: объектное хранилище / Mac владельца), срок **30** суток rolling |
| Целостность | SHA-256 в sidecar; периодическая `rel0-backup-verify.sh` |
| RPO (пилот) | **24 ч** (ежедневный backup) |
| RTO (пилот) | **8 ч** (ручное восстановление + smoke) |

---

## 4. Порядок развёртывания (фазы)

```text
(a) probe-restore синтетики REL0 → (b) deploy contour B @ main SHA → (c) health/smoke синтетика
    → (d) отдельное решение о реальных данных ТОПКОМ
```

### Фаза (a) — проба восстановления (синтетика)

**Артефакт:** `finpilot-staging-REL0-20261028T081545Z.tar.enc`  
**SHA-256:** `57fe4b435d201f5c370a17ff39b16b5ba570f8f519aa1848e7048674f2cbaa1a` (см. DECISIONS · REL0).

**Критерий успеха probe:**

- Временная БД `finpilot_contour_b_probe` (не production DB).
- `alembic_version` = head репозитория на SHA развёртывания.
- Baseline финансов **ООО «Топ»** совпадает с эталоном REL0 verify (read-only counts / контрольные суммы smoke).
- После OK — **DROP** probe DB и удаление временных файлов decrypt.

### Фаза (b) — разворот контура

Образы с **текущего main** на момент окна; миграции один раз через `MIGRATION_DATABASE_URL`.

### Фаза (c) — health и smoke

- `/health/live`, `/health/ready` → 200
- Авторизованный smoke на **синтетической** firm (не ТОПКОМ), без загрузки клиентских файлов.

### Фаза (d) — реальные данные

**Только** после: L1–L4 closed владельцем, `restore_new_server_verified=true` на probe, отдельное письменное «ок» на загрузку ТОПКОМ.

---

## 5. Команды (plan-only, для пошагового одобрения)

Параметры: `HOST` — IP контура B; `DEPLOY_USER=deploy`; `PASSFILE` — путь к passphrase backup (600); `SHA` — product main; `PROBE_DB=finpilot_contour_b_probe`.

| ID | Действие | Команда (шаблон) | Ожидаемый результат | Откат |
| --- | --- | --- | --- | --- |
| **B-01** | Проверка SSH | `ssh ${DEPLOY_USER}@${HOST} 'uname -a && timedatectl'` | Linux, timezone Moscow | — |
| **B-02** | Hardening sshd | `PermitRootLogin no`, `PasswordAuthentication no` + reload sshd | root login denied | restore sshd config backup |
| **B-03** | Firewall base | `ufw allow OpenSSH`, `ufw allow 80,443/tcp`, `ufw enable` | только нужные порты | `ufw disable` |
| **B-04** | fail2ban | установка пакета + jail sshd | banned после N fails | stop fail2ban |
| **B-05** | Docker install | по доке Docker CE pin version | `docker compose version` OK | remove packages |
| **B-06** | Каталог приложения | `sudo install -d -o deploy -m 750 /fin_pilot` | владелец deploy | `rm -rf` (если пусто) |
| **B-07** | Clone/checkout SHA | `git fetch && git checkout ${SHA}` в `/fin_pilot` | HEAD = SHA | checkout prev |
| **B-08** | Probe decrypt | `rel0-backup-verify.sh ${PASSFILE} …/finpilot-staging-REL0-20261028T081545Z.tar.enc` → probe DB | **`REL0_BACKUP_VERIFY_OK`** | DROP probe DB |
| **B-09** | Probe alembic | `SELECT version_num FROM alembic_version` в probe | = repo head | DROP probe |
| **B-10** | Probe baseline | read-only SQL / smoke script на «Топ» | суммы = эталон REL0 | DROP probe |
| **B-11** | Probe cleanup | `DROP DATABASE finpilot_contour_b_probe` + wipe decrypt dir | диск без сырого dump | — |
| **B-12** | Load api image | `docker load` из tarball CI artifact `finpilot-api-release-candidate-${SHA}` | image present | `docker rmi` |
| **B-13** | Load frontend image | аналогично frontend artifact | image present | `docker rmi` |
| **B-14** | `.env` contour B | файл 600, owner deploy, флаги §2.1 | `app` стартует без mock email in prod errors | restore prev .env |
| **B-15** | Migrate | `alembic upgrade head` через one-shot container | one row in alembic_version | restore from backup (B-20) |
| **B-16** | Compose up | `docker compose -p finpilot-contour-b up -d` | all healthy | `compose down` |
| **B-17** | TLS | Caddy obtains cert для домена B | HTTPS valid | revert Caddyfile |
| **B-18** | Health | `curl -fsS https://${DOMAIN}/health/ready` | 200 | logs |
| **B-19** | Smoke synthetic | scripted login + cashflow read | 200, known synthetic totals | — |
| **B-20** | Backup post-deploy | `rel0-backup-create.sh ${PASSFILE}` | `.tar.enc` + sha256 | delete bad backup |
| **B-21** | Offsite copy | scp/rsync `.enc` + `.sha256` offsite | sha256 match | — |
| **B-22** | Rollback drill | документированный откат образов на N-1 SHA | health OK на prev | re-up current |

---

## 6. Откат и аварийное восстановление

1. Остановить трафик (Caddy maintenance / DNS).
2. `docker compose down` (контур B).
3. Restore последнего **verified** `.tar.enc` в новую/ту же БД (как REL0 verify).
4. Поднять предыдущий известный-good образ (тег сохранять при каждом окне).
5. Health + smoke synthetic → решение о reopen.

---

## 7. Что нужно от владельца к **2026-11-06**

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

---

## 8. Ограничения документа

- Не создаёт tenant, firm, платёж, webhook, миграцию без окна.
- Не регистрирует боевой webhook YooKassa / IMAP.
- Не заменяет `ops/rel0/` — при расхождении приоритет у скриптов и MANIFEST в git.
