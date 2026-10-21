# UX-CALENDAR-01 · Календарь: форма, перенос, сопоставление

Статус: **принят владельцем** 2026-10-21.

Это **не** приёмка FA-R03 / FA-R08 и **не** staging write-smoke. Успешные записи на staging (создание плана, сохранение переноса, сопоставление) **не** выполнялись.

Объём приёмки:

- реализация и локальные проверки;
- публикация и успешный CI на product SHA;
- **frontend-only** staging deploy;
- **read-only** staging smoke 2026-10-21.

## Snapshot vs history

| Слой | SHA / revision | Примечание |
| --- | --- | --- |
| **Frontend source (product)** | `15555751aafffe1743e60107508ea3df6ca93724` | commit «feat: clarify calendar plan creation and rescheduling» |
| **Backend source (staging)** | `be9e47af63310f3d5745eadf67dddb0e8c6c9442` | без изменений с FA-R02 фазы A |
| **Schema (staging)** | `20261019_0014` | без изменений |

**Весь стенд одним коммитом не обозначать:** на staging frontend и backend имеют **разные** source SHA.

## Frontend (staging deploy)

| Поле | Значение |
| --- | --- |
| Source SHA | `15555751aafffe1743e60107508ea3df6ca93724` |
| Docker tag | `finpilot-frontend:release-15555751aafffe1743e60107508ea3df6ca93724` |
| Image ID | `sha256:3330c797afceab82eb55a6ce6cdedc5912d49282c1f4bab0b7369c40aa411b56` |
| Platform | **linux/amd64** |
| Bundle (через proxy) | `assets/index-Dh8wFLHG.js` |
| Override | `/var/tmp/finpilot-frontend-1555575/compose.frontend.override.yml` |
| Сборка | `git archive` frontend @ SHA, существующий `frontend/Dockerfile`; backend **не** собирался |

Предыдущий frontend на диске сохранён: `finpilot-frontend:release-7ee85e5` → `sha256:a00f7ddfcb005257654b6fde15951b09e805aadde30bf6b0ad7a51c5daf84697`.

Процедура deploy и откат — [`docs/runbook-staging.md`](../runbook-staging.md) (раздел UX-CALENDAR-01).

## Backend (без recreate в UX-CALENDAR-01)

| Поле | Значение |
| --- | --- |
| Product source SHA | `be9e47af63310f3d5745eadf67dddb0e8c6c9442` |
| Docker tag | `finpilot-api:release-be9e47af63310f3d5745eadf67dddb0e8c6c9442` |
| Override | `/var/tmp/finpilot-release-be9e47a/compose.override.yml` |
| Release record | [`FA-R02-release-phase-A.md`](FA-R02-release-phase-A.md) |

## Доказательства (CI / E2E)

| Проверка | Run / результат |
| --- | --- |
| CI @ `15555751…` | [39479901422](https://github.com/zugrov/fin_pilot/actions/runs/39479901422) — success: frontend 93 tests + build; backend Ruff/Mypy и **464** pytest passed |
| E2E @ `15555751…` | [39479901439](https://github.com/zugrov/fin_pilot/actions/runs/39479901439) — **6** passed |
| Polygon E2E | **7** passed **локально**; в CI **не** запускался |

Перед deploy GitHub API из среды оператора вернул **401**; статусы runs **не** перепроверялись через API и опираются на зафиксированные номера runs и локальный объект git.

## Staging read-only smoke (2026-10-21)

Доступ: SSH-туннель `127.0.0.1:8090`, авторизованный сеанс владельца. Cookies, токены и пароли **не** документируются.

| Пункт | Результат |
| --- | --- |
| Фирма ООО «Топ»; выбор после reload | OK |
| Обзор, Кошельки, Продажи, Календарь | OK |
| Форма «Новая плановая выплата»: пустые сумма и даты; подписи и пояснения | OK |
| Диалог «Перенос ожидания» (acceptance-plan) | OK |
| Изменение даты в черновике + «Отмена» без PATCH | OK (in-page счётчик `fetch` PATCH) |
| После reload due/expected acceptance-plan | **2026-10-25** / **2026-10-27** |
| Блок «Связать с фактической оплатой»: русские подписи | OK |

**Не нажималось:** «Добавить в план», «Сохранить перенос», «Сопоставить». Импорт, commit, reconcile, пересчёты — **нет**.

**Не входило в smoke:** прогноз, бюджет, алерты, импорт, Telegram, beat runtime (отдельно).

### Скриншоты (не в репозитории)

Новые staging-снимки лежат в **agent store** Cursor (не копировались в git):

- `staging-ux-calendar-create-20261021.png`
- `staging-ux-calendar-move-20261021.png`
- `staging-ux-calendar-match-20261021.png`

Старые локальные `ux-calendar-*.png` **не** считаются доказательством этого smoke.

## Safe flags (runtime vs FA-R02 фаза A)

Сверка **значений** api и worker с baseline [`FA-R02-release-phase-A.md`](FA-R02-release-phase-A.md): **совпадают** (`SESSION_INGEST_ENABLED=false`, все `SEND_*` и `POLL_IMAP`/`REFUNDS` — false, `BALANCES_IMPORT_ENABLED=true`, `BILLING_MODE=test`, `EMAIL_PROVIDER_MODE=smtp`, `BILLING_GUARD_BYPASS` absent). Beat **отдельно** в этом smoke **не** проверялся. Флаги **не** менялись.

## Финансовые контроли (после smoke, read-only)

Фирма `company_id=2f346a28-da63-4ab1-a9e8-611fe7e2dd7d` (ООО «Топ»). SQL и UI после smoke:

| Показатель | Значение |
| --- | --- |
| Posted cash transactions | **5** |
| Cash total | **80499.50** |
| Revenue October ex-VAT | **20002.00** |
| Acceptance plan due / expected | **2026-10-25** / **2026-10-27** |

Приёмочные UUID FA-R01.3 — в `docs/roadmap/STATE.json` → `fa_r01_3_acceptance` (**STATE этим закрытием не менялся**).

## Связанные документы

- Актуальный снимок стенда: [`docs/readiness-live.md`](../readiness-live.md)
- Runbook, frontend override и откат: [`docs/runbook-staging.md`](../runbook-staging.md)
- Backend release фазы A: [`FA-R02-release-phase-A.md`](FA-R02-release-phase-A.md)
