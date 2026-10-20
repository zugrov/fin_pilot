# FA-R02 · Staging release · фаза A

Статус: **принята владельцем** 2026-10-20. **Фаза B не выполнялась.**

## Snapshot vs history

| Слой | SHA / revision | Примечание |
| --- | --- | --- |
| **Repo accepted product (G2)** | `be9e47af63310f3d5745eadf67dddb0e8c6c9442` | FA-R02.4 и этап FA-R02 — без изменения |
| **Per-task accepted product SHA** | R02.1 `9fe5c06…`, R02.1b `a78080a…`, R02.2 `aedf0b8…`, R02.3 `ecb7d64…`, R02.4 `be9e47a…` | **Не переписывались** |
| **Staging deployed (до фазы A)** | `7ee85e501735efcfa449ad8f44ef11258e5e4cf2`, schema `20261017_0010` | FA-R01.3 baseline |
| **Staging deployed (после фазы A)** | product **`be9e47a…`**, schema **`20261019_0014`** | этот документ |

## Target

- VPS: SSH `my-vps`, каталог `/fin_pilot`, Compose **`-p finpilot-staging`**
- Доступ: loopback **`127.0.0.1:8090`** (SSH-туннель)
- БД: `finpilot` проекта `finpilot-staging`

## Образы (подтверждённый deploy)

### api / worker / beat (один RC)

| Поле | Значение |
| --- | --- |
| Product source SHA | `be9e47af63310f3d5745eadf67dddb0e8c6c9442` |
| Docker tag | `finpilot-api:release-be9e47af63310f3d5745eadf67dddb0e8c6c9442` |
| **OCI manifest** (VPS `docker inspect` / loaded index) | `sha256:31b6986b3102b434efc65d8d91bce48d58a1a1a78642d3799b7324e3dd652e62` |
| **OCI image config** (GHA manifest `image_id`, тот же rootfs) | `sha256:19f676995efe664069de0f2cd8fad84735a5e899e777ef0f0fee7d562d692f1e` |
| Platform | **linux/amd64** |
| Beat | **один** контейнер |
| Override | `/var/tmp/finpilot-release-be9e47a/compose.override.yml` |
| Команды | `/app/.venv/bin/uvicorn`, `/app/.venv/bin/celery` (worker + beat) |

### Artifact (offline smoke, не HTTP/E2E)

| Поле | Значение |
| --- | --- |
| Workflow commit | `485bbcad88a20d465d5e9754f970cef2e6058db1` |
| GHA run | [39375731256](https://github.com/zugrov/fin_pilot/actions/runs/39375731256) — success |
| Tarball SHA-256 | `6f73a54a5a7be9896963745256c3560b62e06c9d9ec6f33d0eaba0f4cb8a6fcd` |
| VPS path | `/var/tmp/finpilot-release-be9e47a/` |

Product acceptance (до deploy): CI [39316650896](https://github.com/zugrov/fin_pilot/actions/runs/39316650896), E2E [39316650795](https://github.com/zugrov/fin_pilot/actions/runs/39316650795) @ `be9e47a`.

### frontend (без recreate)

| Поле | Значение |
| --- | --- |
| Tag | `finpilot-frontend:release-7ee85e5` |
| Image ID | `sha256:a00f7ddfcb005257654b6fde15951b09e805aadde30bf6b0ad7a51c5daf84697` |
| Product | тот же **7ee85e5**, что до фазы A |

## Maintenance window

| | |
| --- | --- |
| Freeze start (UTC) | **2026-10-20T06:32:11Z** |
| Log | `/var/backups/finpilot/fa-r02-maintenance-20261020T063211Z.log` |
| Миграция | **0010 → 0014** (`20261019_0014`) |
| Health после RC | **live=200, ready=200** |
| Worker | `celery … ready` |
| Beat | один процесс **Up** |

## Backup

| | |
| --- | --- |
| Encrypted | `/var/backups/finpilot/finpilot-staging-FA-R02-20261020T063211Z.tar.enc` |
| Size | 327 712 bytes |
| SHA-256 | `7661414aaaa7b21fadc58508b26393e91346b1183ca924c3fc2aa95b3d2c8a90` |
| Verify | decrypt, `pg_restore --list`, dump/attachments hash — **OK** |
| Offsite Mac | `/Users/maximzugrov/Backups/finpilot-staging/finpilot-staging-FA-R02-20261020T063211Z.tar.enc` — **SHA match** |
| PASSFILE | временный файл оператора **удалён** после offsite |

Manifest внутри архива: schema **0010** на момент freeze, финансовые контроли и image IDs baseline.

## Effective safe flags (override + runtime api/worker/beat)

| Flag | Value |
| --- | --- |
| SESSION_INGEST_ENABLED | **false** |
| SEND_REAL_EMAIL | **false** |
| SEND_EXTERNAL_MESSAGES | **false** |
| SEND_LIVE_PAYMENTS | **false** |
| POLL_IMAP | **false** |
| REFUNDS_ENABLED | **false** |
| BALANCES_IMPORT_ENABLED | **true** |
| BILLING_MODE | **test** |
| EMAIL_PROVIDER_MODE | **smtp** |
| BILLING_GUARD_BYPASS | absent |

`.env` на сервере **не менялся** (allowlists/secrets не документируются).

## Финансовый baseline (сохранён)

| Показатель | Значение |
| --- | --- |
| Posted cash transactions (ООО «Топ») | **5** |
| Cash total | **80499.50** |
| Revenue October ex-VAT | **20002.00** |
| Acceptance plan | **2.00**, due **2026-10-25**, expected **2026-10-27** |
| Plan matches | **0.50** / **0.50** |
| Acceptance UUID | revenue `4a2620cf-…`, rev match `faf5f930-…`, plan `3fdb8da9-…`, plan match `bf5ad3e2-…` (см. `STATE.json` → `fa_r01_3_acceptance`) |

`ingestion_deliveries` после deploy — **пусто** (ожидаемо).

## Browser evidence (не автоматизация)

- **Ручное подтверждение владельца** 2026-10-20: «Всё ок».
- Календарь дополнительно сверен **по скриншоту** — суммы/даты соответствуют baseline.
- Это **не** автоматизированный staging E2E и **не** write-smoke агента.
- Новые ingest / commit / reconcile на staging **не проверялись**.

## Ограничения фазы A

- **Session ingest** остаётся **off** (`SESSION_INGEST_ENABLED=false`).
- **Фаза B** (session ingest на staging, write-smoke ingest/reconcile и т.п.) **не выполнялась**.
- Прогноз/алерты: только просмотр; сохранённый расчёт **не** трактовался как новый пересчёт.

## Инцидент на recreate (postmortem)

| | |
| --- | --- |
| **Причина** | `docker compose up` **без** `--env-file /fin_pilot/.env` → interpolation `POSTGRES_PASSWORD` failed |
| **Нарушение** | error-handler maintenance **auto-start baseline** (api `d552…`, worker/beat `c7ff…`) **после успешной DDL** вместо fail-closed stop + отчёт |
| **Оценочное окно** | **~2026-10-20T06:32:23Z — 06:32:33Z** (оценка по log + `CreatedAt` RC api); **не** утверждать одинаковую длительность для всех сервисов |
| **DB в окне** | признаков новых sent/processed/failed в outbox/billing **не обнаружено** |
| **Внешние провайдеры** | **независимо не проверялись** |
| **Утерянное evidence** | docker events за окно пусто; логи baseline-контейнеров до `force-recreate` **не сохранились** |
| **Error-handler** | scripts/ops **не исправлялись** — только рабочее правило ниже |

### Рабочее правило (будущие операции)

```bash
cd /fin_pilot && docker compose \
  --env-file /fin_pilot/.env \
  -f infra/docker-compose.staging.yml \
  -f /var/tmp/finpilot-release-be9e47a/compose.override.yml \
  -p finpilot-staging …
```

После DDL: **fail-closed** — без автоматического baseline restart, downgrade или удаления volumes.

## Rollback reference (не применялся)

- DB+attachments: backup FA-R02 `.enc` (+ offsite).
- Образы до deploy: api `sha256:d5520080a1cd6c731bcdee102ca00dfa0098622c076b58e6ea2946b1cacd55ae`, worker/beat `sha256:c7ff510499579c8e95ade8e11036a86f4ac91c55bdaac0714e2a30d1e23d490c`, frontend `a00f7dd…`.
- Откат схемы после 0014 — **restore из backup**, не `alembic downgrade`.

## Календарь · UX-долг (не финансовый дефект)

По скриншоту владельца **финансовых расхождений нет**. Зафиксирован UX-долг:

- фиксированные стартовые значения формы;
- неподписанная ожидаемая дата в карточке;
- общая дата переноса;
- технические подписи.

Код и приёмочные данные **не менялись**.

## Handoff

- **FA-R02** остаётся **accepted** (repo product `be9e47a`).
- **Фаза A** — deployed и принята владельцем.
- **current_stage / current_task:** FA-R03 / FA-R03.1 — **planned**.
- **allowed_next_action:** read-only подготовка первого профиля выгрузок 1С и контрольных образцов — **только по отдельному разрешению**; реализация, реальные данные и интеграции **не** разрешены автоматически.
